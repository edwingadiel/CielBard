"""Fake MMOMinion client: a rule-free Lua mirror that drives the shipped CielBard engine.

The client owns a `lupa` `LuaRuntime`, loads `CielBard/CielBard_Data.lua` and
`CielBard/CielBard_Rotation.lua` verbatim, publishes exactly the globals the engine
reads, and captures the cast requests the engine issues. It holds no game rules: every
value it reports is one the caller wrote into it.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from lupa import LuaError, LuaRuntime, lua_type

__all__ = [
    "ActionSpec",
    "ActionView",
    "BuffView",
    "CastRequest",
    "ClientRejection",
    "EntityView",
    "FakeClient",
    "LuaBridgeError",
    "PlayerView",
    "PotionView",
    "lua_method",
]

_DATA_FILE = "CielBard_Data.lua"
_ROTATION_FILE = "CielBard_Rotation.lua"

# Lua helper factories. Every callable the engine reaches must answer `type(x) ==
# "function"`; a bare Python callable answers "userdata" on lupa 2.8, which would make
# the engine take its "API missing" fallback paths (see FakeClient._BOOTSTRAP).
_BOOTSTRAP = """
return {
    func = function(py) return function(...) return py(...) end end,
    method = function(py) return function(self, ...) return py(self, ...) end end,
    gc = function() collectgarbage("collect") end,
}
"""

# How many pulses may pass between the manual, quiescent-point Lua collections that
# replace the automatic collector (see FakeClient._install_gc_guard).
_GC_EVERY_PULSES = 64

# Lua 5.5 (the interpreter lupa 2.8 embeds) seeds its string hash from the wall clock,
# so `pairs()` over a string-keyed table iterates in a different order in every
# `LuaRuntime`. The shipped engine iterates `D.Songs`, `D.AoEDefaults` and
# `E.state.codas` with `pairs`, which would make identical fights diverge and breaks
# SPEC 0.1 rule 4 (determinism). The engine file is untouchable, but the *environment*
# the simulator hands it is ours, so `pairs` is replaced with a key-sorted version.
# Pure array tables (buff lists, EntityList results) already iterate in index order and
# take the cheap path with no sort.
_DETERMINISTIC_PAIRS = """
local rawpairs = pairs
local sort, type_, tostring_ = table.sort, type, tostring
local function keyorder(a, b)
    local ta, tb = type_(a), type_(b)
    if ta ~= tb then return ta < tb end
    if ta == "number" or ta == "string" then return a < b end
    return tostring_(a) < tostring_(b)
end
function pairs(t)
    if type_(t) ~= "table" then return rawpairs(t) end
    local keys, n, plain = nil, 0, true
    for k in rawpairs(t) do
        n = n + 1
        if plain and (type_(k) ~= "number" or k ~= n) then plain = false end
        if keys == nil then keys = { k } else keys[n] = k end
    end
    if plain or n < 2 then return rawpairs(t) end
    sort(keys, keyorder)
    local i = 0
    return function()
        i = i + 1
        local k = keys[i]
        if k == nil then return nil end
        return k, t[k]
    end
end
"""


def lua_method(fn):
    """Make a method callable both as Lua `obj:M(a)` and as Python `obj.M(a)`.

    lupa passes the receiver again for some runtime/version combinations; drop a
    leading argument that is the receiver itself.
    """

    @functools.wraps(fn)
    def wrapper(self, *args):
        if args and args[0] is self:
            args = args[1:]
        return fn(self, *args)

    return wrapper


class LuaBridgeError(RuntimeError):
    """Raised when the Lua files cannot be loaded or the engine raises out of Step."""


@dataclass(frozen=True)
class ActionSpec:
    """The static shape of one action as the client must present it."""

    action_id: int
    name: str
    is_gcd: bool
    self_target: bool
    recast_s: float
    max_charges: int = 1
    status_gained_id: int = 0


@dataclass
class ActionView:
    """Per-pulse mutable action state written by the core, read by the engine.

    `ready` is the core's verdict for `IsReady` *ignoring* targeting; the client applies
    the self-target rule of SPEC 3.5 on top of it.
    """

    cd: float = 0.0
    cdmax: float = 0.0
    isoncd: bool = False
    usable: bool = True
    ready: bool = False
    highlighted: bool = False


@dataclass(frozen=True)
class BuffView:
    """One status entry as `Player.buffs` / `entity.buffs` present it."""

    id: int
    ownerid: int
    duration: float


@dataclass
class EntityView:
    """One entity as `EntityList` and `Player:GetTarget()` present it."""

    id: int
    name: str
    alive: bool = True
    targetable: bool = True
    incombat: bool = True
    los: bool = True
    distance2d: float = 3.0
    hp_current: float = 1.0e9
    hp_max: float = 1.0e9
    hp_percent: float = 100.0
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    buffs: tuple[BuffView, ...] = ()


@dataclass
class PlayerView:
    """The local player as the engine reads it."""

    id: int = 100
    job: int = 23
    alive: bool = True
    incombat: bool = True
    hp_percent: float = 100.0
    gauge: tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
    buffs: tuple[BuffView, ...] = ()
    locked: bool = False  # -> MIsLocked()
    casting: bool = False  # -> MIsCasting() and ActionList:IsCasting()
    loading: bool = False  # -> MIsLoading()


@dataclass(frozen=True)
class PotionView:
    """One inventory potion, addressed by MMOMinion's hqid."""

    hqid: int
    action_id: int
    ready: bool
    cd: float = 0.0
    cdmax: float = 270.0


@dataclass(frozen=True)
class CastRequest:
    """One `action:Cast(target)` or `item:Cast(player)` the engine issued."""

    action_id: int
    target_id: int
    is_item: bool
    request_ms: int
    hqid: int = 0  # item requests only


@dataclass(frozen=True)
class ClientRejection:
    """A Cast the client refused (returned false to Lua)."""

    action_id: int
    target_id: int
    reason: str  # "not-ready" | "self-target-mismatch" | "unknown-action"
    request_ms: int


# ---------------------------------------------------------------------------
# Lua-facing proxies. These are plain Python objects (userdata in Lua); only the
# containers the engine calls valid()/pairs() on are real Lua tables.
# ---------------------------------------------------------------------------


class _LuaFacing:
    """Base for objects Lua reads attributes from.

    A missing attribute reads as `nil` instead of raising, which is what a Lua table
    would do. The engine reads optional fields such as `los2` and `dispellable`.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return None


class _Pos(_LuaFacing):
    """A world position with the x/y/z fields `distance3` reads."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z


class _Hp(_LuaFacing):
    """The `entity.hp` sub-table: current, max, percent."""

    __slots__ = ("current", "max", "percent")

    def __init__(self) -> None:
        self.current = 0.0
        self.max = 0.0
        self.percent = 100.0


class _CastingInfo(_LuaFacing):
    """`Player.castinginfo`: the last cast id and milliseconds since it started."""

    __slots__ = ("lastcastid", "timesincecast")

    def __init__(self) -> None:
        self.lastcastid = 0
        self.timesincecast = 999999


class _EntityProxy(_LuaFacing):
    """One entity exposed to Lua; `buffs` is a real Lua table of Lua tables."""

    __slots__ = (
        "id",
        "name",
        "alive",
        "targetable",
        "incombat",
        "los",
        "los2",
        "distance2d",
        "hp",
        "pos",
        "buffs",
        "_buff_pool",
        "_buff_attached",
        "_buff_key",
        "_field_key",
    )

    def __init__(self, entity_id: int, buffs_table: Any) -> None:
        self.id = entity_id
        self.name = ""
        self.alive = True
        self.targetable = True
        self.incombat = True
        self.los = True
        self.los2 = True
        self.distance2d = 0.0
        self.hp = _Hp()
        self.pos = _Pos()
        self.buffs = buffs_table
        self._buff_pool: list[Any] = []
        self._buff_attached = 0
        self._buff_key: tuple = ()
        self._field_key: tuple = ()


class _PlayerProxy(_LuaFacing):
    """`Player`; `gauge` and `buffs` are real Lua tables, `GetTarget` a Lua function."""

    __slots__ = (
        "id",
        "job",
        "alive",
        "incombat",
        "hp",
        "gauge",
        "buffs",
        "castinginfo",
        "GetTarget",
        "_buff_pool",
        "_buff_attached",
        "_buff_key",
        "_gauge_key",
        "_field_key",
    )

    def __init__(self, player_id: int, gauge_table: Any, buffs_table: Any) -> None:
        self.id = player_id
        self.job = 23
        self.alive = True
        self.incombat = True
        self.hp = _Hp()
        self.hp.current = 1.0
        self.hp.max = 1.0
        self.hp.percent = 100.0
        self.gauge = gauge_table
        self.buffs = buffs_table
        self.castinginfo = _CastingInfo()
        self.GetTarget = None
        self._buff_pool: list[Any] = []
        self._buff_attached = 0
        self._buff_key: tuple = ()
        self._gauge_key: tuple = ()
        self._field_key: tuple = ()


class _ActionProxy(_LuaFacing):
    """One `ActionList:Get(1, id)` result, cached for the lifetime of the client."""

    __slots__ = (
        "id",
        "name",
        "cd",
        "cdmax",
        "isoncd",
        "usable",
        "recasttime",
        "highlighted",
        "statusgainedid",
        "isready",
        "IsReady",
        "Cast",
        "_client",
        "_spec",
        "_ready",
        "_known",
        "_key",
    )

    def __init__(self, client: "FakeClient", spec: ActionSpec, known: bool) -> None:
        self.id = spec.action_id
        self.name = spec.name
        self.cd = 0.0
        self.cdmax = 0.0
        self.isoncd = False
        self.usable = known
        self.recasttime = spec.recast_s
        self.highlighted = False
        self.statusgainedid = spec.status_gained_id
        self.isready = False
        self._client = client
        self._spec = spec
        self._ready = False
        self._known = known
        self._key: tuple = ()
        self.IsReady = None
        self.Cast = None

    @lua_method
    def is_ready(self, target_id: Any = None, *_rest: Any) -> bool:
        """`ac:IsReady(targetID)`: readiness plus the live self-target rule."""
        client = self._client
        try:
            if self.usable is False:
                return False
            if self._spec.self_target and int(target_id or 0) != client.player_id:
                return False
            return bool(self._ready)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for pcall
            client._note_error(exc, "IsReady(%d)" % self._spec.action_id)
            raise

    @lua_method
    def cast(self, target_id: Any = None, *_rest: Any) -> bool:
        """`ac:Cast(targetID)`: record a request, or a rejection with its reason."""
        client = self._client
        try:
            tid = int(target_id or 0)
            if not self._known:
                client._reject(self.id, tid, "unknown-action")
                return False
            if self.usable is False or not self._ready:
                client._reject(self.id, tid, "not-ready")
                return False
            if self._spec.self_target and tid != client.player_id:
                client._reject(self.id, tid, "self-target-mismatch")
                return False
            client._requests.append(CastRequest(self.id, tid, False, client._now_ms))
            return True
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for pcall
            client._note_error(exc, "Cast(%d)" % self.id)
            raise


class _ActionListProxy(_LuaFacing):
    """`ActionList` with `Get(type, id)` and `IsCasting()`."""

    __slots__ = ("Get", "IsCasting", "_client")

    def __init__(self, client: "FakeClient") -> None:
        self._client = client
        self.Get = None
        self.IsCasting = None

    @lua_method
    def get(self, _action_type: Any = None, action_id: Any = None, *_rest: Any) -> Any:
        """Return the cached action proxy for `action_id` (a stub when unknown)."""
        client = self._client
        try:
            return client._action_for(int(action_id or 0))
        except Exception as exc:  # noqa: BLE001
            client._note_error(exc, "ActionList:Get")
            raise

    @lua_method
    def is_casting(self, *_rest: Any) -> bool:
        """Mirror of `PlayerView.casting`."""
        return bool(self._client._player_casting)


class _ItemActionProxy(_LuaFacing):
    """The action object behind a potion: `id`, `isoncd`, `cd`, `cdmax`."""

    __slots__ = ("id", "isoncd", "cd", "cdmax")

    def __init__(self, action_id: int) -> None:
        self.id = action_id
        self.isoncd = False
        self.cd = 0.0
        self.cdmax = 0.0


class _ItemProxy(_LuaFacing):
    """One inventory potion: `hqid`, `IsReady`, `Cast`, `GetAction`."""

    __slots__ = ("hqid", "IsReady", "Cast", "GetAction", "_client", "_action", "_ready")

    def __init__(self, client: "FakeClient", hqid: int, action_id: int) -> None:
        self.hqid = hqid
        self._client = client
        self._action = _ItemActionProxy(action_id)
        self._ready = False
        self.IsReady = None
        self.Cast = None
        self.GetAction = None

    @lua_method
    def is_ready(self, _target_id: Any = None, *_rest: Any) -> bool:
        """`item:IsReady(playerId)`."""
        return bool(self._ready)

    @lua_method
    def cast(self, target_id: Any = None, *_rest: Any) -> bool:
        """`item:Cast(playerId)`: record an item request or a rejection."""
        client = self._client
        try:
            tid = int(target_id or 0)
            if not self._ready:
                client._reject(self._action.id, tid, "not-ready")
                return False
            client._requests.append(
                CastRequest(self._action.id, tid, True, client._now_ms, self.hqid)
            )
            return True
        except Exception as exc:  # noqa: BLE001
            client._note_error(exc, "item:Cast(%d)" % self.hqid)
            raise

    @lua_method
    def get_action(self, *_rest: Any) -> Any:
        """`item:GetAction()`."""
        return self._action


def _scalar(value: Any) -> Any:
    """Convert one Lua value to a plain Python scalar, or None for anything else."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return None


class FakeClient:
    """A minimal, faithful stand-in for the MMOMinion Lua API.

    Owns the LuaRuntime and the Lua-side mirror of game state. Holds no game rules:
    every value it reports is one the core wrote.
    """

    #: Fields of `CielBardEngine.state` reported by `engine_state()`.
    STATE_FIELDS = (
        "lastDecision",
        "lastActionName",
        "weavesSinceGCD",
        "gcdsSinceRaging",
        "currentSong",
        "songRemaining",
        "charges",
        "chargeRemaining",
        "maxCharges",
        "chargeInfo",
        "ttk",
        "ttkConfidence",
        "ttkBand",
        "gcdRemaining",
        "enemyCount",
        "lastRequestID",
        "lastObservedCastID",
        "multiDotTargetID",
        "multiDotTargetName",
        "potionName",
        "potionActionID",
    )

    def __init__(
        self,
        repo_root: Path,
        specs: Sequence[ActionSpec],
        *,
        player_id: int = 100,
        target_id: int = 200,
        debug_sink: Callable[[str], None] | None = None,
    ) -> None:
        """Create the runtime, load the shipped Lua, publish globals.

        Raises LuaBridgeError if either Lua file is missing or fails to load.
        """
        self.repo_root = Path(repo_root)
        self.player_id = int(player_id)
        self.target_id = int(target_id)
        self.unknown_action_ids: set[int] = set()

        self._debug_sink = debug_sink
        self._now_ms = 0
        self._closed = False
        self._requests: list[CastRequest] = []
        self._rejections: list[ClientRejection] = []
        self._errors: list[str] = []
        self._player_casting = False
        self._player_locked = False
        self._player_loading = False

        self._lua = LuaRuntime(unpack_returned_tuples=True)
        self._lua.execute(_DETERMINISTIC_PAIRS)
        mk = self._lua.execute(_BOOTSTRAP)
        self._mk_func = mk["func"]
        self._mk_method = mk["method"]
        self._lua_gc = mk["gc"]
        self._gc_pulses = 0
        self._install_gc_guard()

        self._load_lua_files()

        globals_ = self._lua.globals()
        self._data = globals_["CielBardData"]
        self._engine = globals_["CielBardEngine"]
        if self._data is None or self._engine is None:
            raise LuaBridgeError("CielBardData / CielBardEngine missing after load")

        self._specs: dict[int, ActionSpec] = {int(s.action_id): s for s in specs}
        self._actions: dict[int, _ActionProxy] = {}
        self._action_keys: dict[int, tuple] = {}
        for spec in specs:
            self._actions[int(spec.action_id)] = self._make_action(spec, True)

        self._gauge_table = self._lua.table()
        for index in range(1, 6):
            self._gauge_table[index] = 0
        self._player = _PlayerProxy(self.player_id, self._gauge_table, self._lua.table())
        self._player.GetTarget = self._mk_method(self._get_target)

        self._action_list = _ActionListProxy(self)
        self._action_list.Get = self._mk_method(self._action_list.get)
        self._action_list.IsCasting = self._mk_method(self._action_list.is_casting)

        self._entities: dict[int, _EntityProxy] = {}
        self._entities_all = self._lua.table()
        self._entities_combat = self._lua.table()
        self._entity_ids_all: list[int] = []
        self._entity_ids_combat: list[int] = []
        self._target: _EntityProxy | None = None

        self._items: dict[int, _ItemProxy] = {}

        globals_["Now"] = self._mk_func(self._lua_now)
        globals_["MIsLoading"] = self._mk_func(self._lua_is_loading)
        globals_["MIsLocked"] = self._mk_func(self._lua_is_locked)
        globals_["MIsCasting"] = self._mk_func(self._lua_is_casting)
        globals_["EntityList"] = self._mk_func(self._lua_entity_list)
        globals_["GetItem"] = self._mk_func(self._lua_get_item)
        globals_["d"] = self._mk_func(self._lua_debug)
        globals_["Player"] = self._player
        globals_["ActionList"] = self._action_list

        self._lua.execute(
            "__cielbard_step = function(viaACR)\n"
            "  local handler = function(msg) return debug.traceback(tostring(msg), 2) end\n"
            "  local ok, res = xpcall(CielBardEngine.Step, handler, viaACR)\n"
            "  return ok, res\n"
            "end"
        )
        self._step_fn = self._lua.globals()["__cielbard_step"]
        self.config: Any = None

    # --- construction helpers -------------------------------------------

    def _install_gc_guard(self) -> None:
        """Take the Lua collector off automatic and drive it from `step` instead.

        lupa 2.8 embeds Lua 5.5, and a collection cycle that runs *inside* a
        Lua-to-Python call can leave a Python-object wrapper pointing at the wrong
        object: `Player.castinginfo` starts reading back as some cached action proxy,
        the engine stops observing its own casts, and identical fights diverge
        (SPEC 0.1 rule 4). Every Python object the engine can reach is owned by a
        Python-side container for the client's whole life, so nothing the collector
        would reclaim is load-bearing; only the short-lived wrappers are. Stopping
        the automatic collector and running a full collection from `step`, between
        pulses, when no Lua call is in flight, is therefore both safe and enough to
        keep memory flat.
        """
        self._lua.execute('collectgarbage("stop")')

    def _load_lua_files(self) -> None:
        """Execute the two shipped Lua files, newest state last."""
        for name in (_DATA_FILE, _ROTATION_FILE):
            path = self.repo_root / "CielBard" / name
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise LuaBridgeError(f"cannot read {path}: {exc}") from exc
            try:
                self._lua.execute(source)
            except LuaError as exc:
                raise LuaBridgeError(f"cannot load {path}: {exc}") from exc

    def _make_action(self, spec: ActionSpec, known: bool) -> _ActionProxy:
        """Build one action proxy with its Lua-callable IsReady / Cast."""
        proxy = _ActionProxy(self, spec, known)
        proxy.IsReady = self._mk_method(proxy.is_ready)
        proxy.Cast = self._mk_method(proxy.cast)
        return proxy

    def _action_for(self, action_id: int) -> _ActionProxy:
        """Cached action proxy; unknown ids get a permanently unusable stub."""
        proxy = self._actions.get(action_id)
        if proxy is not None:
            return proxy
        self.unknown_action_ids.add(action_id)
        stub_spec = ActionSpec(
            action_id=action_id,
            name="Unknown %d" % action_id,
            is_gcd=False,
            self_target=False,
            recast_s=0.0,
            max_charges=1,
            status_gained_id=0,
        )
        stub = self._make_action(stub_spec, False)
        stub.usable = False
        stub.recasttime = 0.0
        self._actions[action_id] = stub
        return stub

    # --- Lua globals -----------------------------------------------------

    def _lua_now(self, *_rest: Any) -> int:
        return self._now_ms

    def _lua_is_loading(self, *_rest: Any) -> bool:
        return self._player_loading

    def _lua_is_locked(self, *_rest: Any) -> bool:
        return self._player_locked

    def _lua_is_casting(self, *_rest: Any) -> bool:
        return self._player_casting

    def _lua_entity_list(self, filter_text: Any = None, *_rest: Any) -> Any:
        try:
            text = filter_text if isinstance(filter_text, str) else ""
            if "incombat" in text:
                return self._entities_combat
            return self._entities_all
        except Exception as exc:  # noqa: BLE001
            self._note_error(exc, "EntityList")
            raise

    def _lua_get_item(self, hqid: Any = None, _bags: Any = None, *_rest: Any):
        try:
            item = self._items.get(int(hqid or 0))
            if item is None:
                return None, None
            return item, item._action
        except Exception as exc:  # noqa: BLE001
            self._note_error(exc, "GetItem")
            raise

    def _lua_debug(self, message: Any = None, *_rest: Any) -> None:
        if self._debug_sink is not None:
            self._debug_sink(str(message))

    @lua_method
    def _get_target(self, *_rest: Any) -> Any:
        try:
            return self._target
        except Exception as exc:  # noqa: BLE001
            self._note_error(exc, "Player:GetTarget")
            raise

    # --- lifecycle -------------------------------------------------------

    def init_engine(self, config_overrides: Mapping[str, Any] | None = None) -> None:
        """Deep-copy CielBardData.Defaults, apply overrides, call CielBardEngine.Init.

        Override keys use dotted paths for nested tables, matching the shipped GUI's
        flat persistence format: `"abilities.ApexArrow"`, `"aoeTargets.Ladonsbite"`.
        A key that does not exist in Defaults raises KeyError (typo protection); pass
        `"_allow_new": True` in the mapping to bypass that for forward compatibility.
        """
        config = self._deep_copy(self._data["Defaults"])
        overrides = dict(config_overrides or {})
        allow_new = bool(overrides.pop("_allow_new", False))
        for dotted, value in overrides.items():
            self._apply_override(config, str(dotted), value, allow_new)
        self.config = config
        self._engine.Init(config)

    def _deep_copy(self, value: Any) -> Any:
        """Copy a Lua table (recursively) into fresh Lua tables."""
        if lua_type(value) != "table":
            return value
        copy = self._lua.table()
        for key, child in value.items():
            copy[key] = self._deep_copy(child)
        return copy

    def _to_lua(self, value: Any) -> Any:
        """Convert a Python override value; mappings and sequences become Lua tables."""
        if isinstance(value, Mapping):
            table = self._lua.table()
            for key, child in value.items():
                table[key] = self._to_lua(child)
            return table
        if isinstance(value, (list, tuple)):
            table = self._lua.table()
            for index, child in enumerate(value, start=1):
                table[index] = self._to_lua(child)
            return table
        return value

    def _apply_override(self, config: Any, dotted: str, value: Any, allow_new: bool) -> None:
        """Write one dotted-path override into the Lua config table."""
        parts = dotted.split(".")
        node = config
        for part in parts[:-1]:
            child = node[part]
            if lua_type(child) != "table":
                if not allow_new:
                    raise KeyError(f"unknown config path segment {part!r} in {dotted!r}")
                child = self._lua.table()
                node[part] = child
            node = child
        leaf = parts[-1]
        if not allow_new and node[leaf] is None:
            raise KeyError(f"unknown config key {dotted!r}")
        node[leaf] = self._to_lua(value)

    def warnings(self) -> list[str]:
        """CielBardEngine.GetConfigurationWarnings() as a Python list."""
        table = self._engine.GetConfigurationWarnings()
        if lua_type(table) != "table":
            return []
        return [str(v) for v in table.values()]

    def close(self) -> None:
        """Drop the Lua runtime. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._step_fn = None
        self._engine = None
        self._data = None
        self.config = None
        self._actions.clear()
        self._entities.clear()
        self._items.clear()
        self._target = None
        self._player = None
        self._action_list = None
        self._entities_all = None
        self._entities_combat = None
        self._gauge_table = None
        self._mk_func = None
        self._mk_method = None
        self._lua_gc = None
        self._lua = None

    # --- per-pulse writes ------------------------------------------------

    def set_time(self, now_ms: int) -> None:
        """Set the value `Now()` returns. Must be monotonic non-decreasing."""
        value = int(now_ms)
        if value < self._now_ms:
            raise ValueError(f"set_time({value}) is before the current time {self._now_ms}")
        self._now_ms = value

    def set_player(self, view: PlayerView) -> None:
        """Mirror one PlayerView into the Lua-visible Player object."""
        player = self._player
        self.player_id = int(view.id)
        self._player_locked = bool(view.locked)
        self._player_casting = bool(view.casting)
        self._player_loading = bool(view.loading)
        key = (view.id, view.job, view.alive, view.incombat, view.hp_percent)
        if key != player._field_key:
            player._field_key = key
            player.id = int(view.id)
            player.job = int(view.job)
            player.alive = bool(view.alive)
            player.incombat = bool(view.incombat)
            player.hp.percent = float(view.hp_percent)
            player.hp.current = float(view.hp_percent)
            player.hp.max = 100.0
        gauge = tuple(view.gauge)
        if gauge != player._gauge_key:
            player._gauge_key = gauge
            table = self._gauge_table
            for index in range(1, 6):
                table[index] = gauge[index - 1] if index <= len(gauge) else 0
        self._sync_buffs(player, view.buffs)

    def set_target(self, view: EntityView | None) -> None:
        """None makes Player:GetTarget() return nil."""
        if view is None:
            self._target = None
            return
        self._target = self._entity_proxy(view)

    def set_entities(self, views: Sequence[EntityView]) -> None:
        """The EntityList(filter) result. The filter string is ignored except that
        `incombat` in the filter drops entities with `incombat=False`."""
        all_ids: list[int] = []
        combat_ids: list[int] = []
        for view in views:
            self._entity_proxy(view)
            all_ids.append(int(view.id))
            if view.incombat:
                combat_ids.append(int(view.id))
        if all_ids != self._entity_ids_all:
            self._rebuild_entity_table(self._entities_all, self._entity_ids_all, all_ids)
            self._entity_ids_all = all_ids
        if combat_ids != self._entity_ids_combat:
            self._rebuild_entity_table(
                self._entities_combat, self._entity_ids_combat, combat_ids
            )
            self._entity_ids_combat = combat_ids

    def _rebuild_entity_table(self, table: Any, old_ids: Sequence[int], new_ids: Sequence[int]):
        """Key the Lua entity table by entity id, dropping ids that left."""
        new_set = set(new_ids)
        for entity_id in old_ids:
            if entity_id not in new_set:
                table[entity_id] = None
        for entity_id in new_ids:
            table[entity_id] = self._entities[entity_id]

    def _entity_proxy(self, view: EntityView) -> _EntityProxy:
        """Get-or-create the proxy for `view.id` and refresh its scalar fields."""
        entity_id = int(view.id)
        proxy = self._entities.get(entity_id)
        if proxy is None:
            proxy = _EntityProxy(entity_id, self._lua.table())
            self._entities[entity_id] = proxy
        key = (
            view.name,
            view.alive,
            view.targetable,
            view.incombat,
            view.los,
            view.distance2d,
            view.hp_current,
            view.hp_max,
            view.hp_percent,
            view.pos,
        )
        if key != proxy._field_key:
            proxy._field_key = key
            proxy.name = view.name
            proxy.alive = bool(view.alive)
            proxy.targetable = bool(view.targetable)
            proxy.incombat = bool(view.incombat)
            proxy.los = bool(view.los)
            proxy.los2 = bool(view.los)
            proxy.distance2d = float(view.distance2d)
            proxy.hp.current = float(view.hp_current)
            proxy.hp.max = float(view.hp_max)
            proxy.hp.percent = float(view.hp_percent)
            proxy.pos.x, proxy.pos.y, proxy.pos.z = (float(c) for c in view.pos)
        self._sync_buffs(proxy, view.buffs)
        return proxy

    def _sync_buffs(self, holder: Any, buffs: Sequence[BuffView]) -> None:
        """Mutate a pre-allocated Lua buff table in place; grow or nil out surplus."""
        key = tuple((b.id, b.ownerid, b.duration) for b in buffs)
        if key == holder._buff_key:
            return
        holder._buff_key = key
        pool = holder._buff_pool
        table = holder.buffs
        count = len(key)
        while len(pool) < count:
            pool.append(self._lua.table())
        for index in range(count):
            entry = pool[index]
            buff_id, owner_id, duration = key[index]
            entry["id"] = buff_id
            entry["ownerid"] = owner_id
            entry["duration"] = duration
        attached = holder._buff_attached
        if attached < count:
            for index in range(attached, count):
                table[index + 1] = pool[index]
        elif attached > count:
            for index in range(count, attached):
                table[index + 1] = None
        holder._buff_attached = count

    def set_action(self, action_id: int, view: ActionView) -> None:
        """Write one action's per-pulse state."""
        proxy = self._action_for(int(action_id))
        key = (view.cd, view.cdmax, view.isoncd, view.usable, view.ready, view.highlighted)
        if key == proxy._key:
            return
        proxy._key = key
        proxy.cd = float(view.cd)
        proxy.cdmax = float(view.cdmax)
        proxy.isoncd = bool(view.isoncd)
        proxy.usable = bool(view.usable)
        proxy.highlighted = bool(view.highlighted)
        proxy._ready = bool(view.ready)
        proxy.isready = bool(view.ready)

    def set_actions(self, views: Mapping[int, ActionView]) -> None:
        """Bulk form; preferred on the hot path."""
        set_action = self.set_action
        for action_id, view in views.items():
            set_action(action_id, view)

    def set_recast(self, action_id: int, recast_s: float) -> None:
        """Override an action's `recasttime` (the GCD recast changes with haste)."""
        self._action_for(int(action_id)).recasttime = float(recast_s)

    def set_last_cast(self, action_id: int, time_since_ms: int) -> None:
        """Mirror `Player.castinginfo`; reset `time_since_ms` to 0 at execution."""
        info = self._player.castinginfo
        info.lastcastid = int(action_id)
        info.timesincecast = int(time_since_ms)

    def set_potions(self, potions: Sequence[PotionView]) -> None:
        """Publishes GetItem(hqid, bags). An empty sequence removes every potion but
        keeps GetItem defined (the engine checks `type(GetItem) == "function"`)."""
        wanted = {int(p.hqid): p for p in potions}
        for hqid in list(self._items):
            if hqid not in wanted:
                del self._items[hqid]
        for hqid, view in wanted.items():
            item = self._items.get(hqid)
            if item is None or item._action.id != int(view.action_id):
                item = _ItemProxy(self, hqid, int(view.action_id))
                item.IsReady = self._mk_method(item.is_ready)
                item.Cast = self._mk_method(item.cast)
                item.GetAction = self._mk_method(item.get_action)
                self._items[hqid] = item
            item._ready = bool(view.ready)
            action = item._action
            # SPEC 3.4: an action that is off cooldown reports cd=0, cdmax=0,
            # isoncd=false. PotionView's cd/cdmax describe the rolling cooldown.
            if view.ready:
                action.isoncd = False
                action.cd = 0.0
                action.cdmax = 0.0
            else:
                action.isoncd = True
                action.cd = float(view.cd)
                action.cdmax = float(view.cdmax)

    # --- pulse -----------------------------------------------------------

    def step(self) -> bool:
        """Call CielBardEngine.Step(false). Returns the engine's boolean.

        Any Lua error is wrapped in LuaBridgeError, with the Lua traceback in the
        message and the pulse's `now_ms` appended.
        """
        if self._closed:
            raise LuaBridgeError("step() on a closed client")
        self._gc_pulses += 1
        if self._gc_pulses >= _GC_EVERY_PULSES:
            # Quiescent point: no Lua call is in flight, so a collection here cannot
            # invalidate a wrapper the engine is holding. See _install_gc_guard.
            self._gc_pulses = 0
            self._lua_gc()
        try:
            ok, result = self._step_fn(False)
        except LuaBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised into LuaBridgeError
            raise LuaBridgeError(f"{type(exc).__name__}: {exc} @ {self._now_ms}ms") from exc
        if not ok:
            raise LuaBridgeError(f"{result} @ {self._now_ms}ms")
        return result is True

    def take_requests(self) -> list[CastRequest]:
        """Drain and return the requests issued since the last drain."""
        drained = self._requests
        self._requests = []
        return drained

    def take_rejections(self) -> list[ClientRejection]:
        """Drain and return the refusals recorded since the last drain."""
        drained = self._rejections
        self._rejections = []
        return drained

    def _reject(self, action_id: int, target_id: int, reason: str) -> None:
        """Record one client-side refusal."""
        self._rejections.append(
            ClientRejection(int(action_id), int(target_id), reason, self._now_ms)
        )

    def _note_error(self, exc: BaseException, where: str) -> None:
        """Record an exception raised inside a Lua-facing callback."""
        self._errors.append(f"{type(exc).__name__}: {exc} @ {self._now_ms}ms in {where}")

    # --- diagnostics -----------------------------------------------------

    def engine_state(self) -> dict[str, Any]:
        """Scalar fields of CielBardEngine.state, as plain Python.

        Includes at least: lastDecision, lastActionName, weavesSinceGCD, currentSong,
        songRemaining, charges, chargeRemaining, ttk, ttkBand, gcdRemaining,
        gcdsSinceRaging, codaCount (computed via CielBardEngine.CodaCount()).
        """
        state = self._engine.state
        out: dict[str, Any] = {}
        for name in self.STATE_FIELDS:
            out[name] = _scalar(state[name])
        out["codaCount"] = int(self._engine.CodaCount() or 0)
        return out

    @property
    def errors(self) -> list[str]:
        """Exceptions raised inside client callbacks and swallowed by Lua's pcall."""
        return self._errors

    @property
    def lua(self) -> Any:
        """The LuaRuntime, for diagnostics and tests."""
        return self._lua

    @property
    def engine(self) -> Any:
        """The Lua `CielBardEngine` table, for diagnostics and tests."""
        return self._engine

    @property
    def data(self) -> Any:
        """The Lua `CielBardData` table, for diagnostics and tests."""
        return self._data

    @property
    def now_ms(self) -> int:
        """The value `Now()` currently returns."""
        return self._now_ms

    @property
    def target(self) -> Any:
        """The Lua-facing proxy `Player:GetTarget()` returns, or None."""
        return self._target
