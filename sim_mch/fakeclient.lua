-- A time-stepped imitation of the MMOMinion client for a level-100 Machinist.
--
-- The shipped engine is driven pulse by pulse and every game rule that shapes
-- the rotation is enforced here: the GCD and its 1.5 s Overheated variant,
-- animation lock, charged cooldowns, Heat and Battery, statuses, the combo,
-- Wildfire hit counting, the Queen's lockout, the potion and its cooldown.
-- There is no damage in this file: it produces a cast log, and sim_mch/core.py
-- prices it afterwards. Machinist has no random procs, so the log is a pure
-- function of the configuration.
--
-- Inputs, published as globals before this file runs:
--   SIM_ACTIONS, SIM_STATUSES, SIM_JOB   the JSON tables under sim_mch/data
--   SIM_CFG                              run configuration (see sim_mch/core.py)
-- Load order: CielMachinist_Data.lua, this file, CielMachinist_Rotation.lua.

local ACT, STA, JOB, CFG = SIM_ACTIONS, SIM_STATUSES, SIM_JOB, SIM_CFG
local A = CielMachinistData.Actions

-- The client clock does not start at zero: the engine rate-limits some work
-- (the inventory scan) against Now(), and a live client's tick count is large.
CLOCK0 = 100000
clock = CLOCK0 -- milliseconds
Now = function() return clock end
MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end

-- Small deterministic generator for latency jitter; Lua's own math.random is
-- seeded from the wall clock on some builds.
local lcg = (tonumber(CFG.seed) or 1) % 2147483647
local function jitter()
    local span = tonumber(CFG.jitter_ms) or 0
    if span <= 0 then return 0 end
    lcg = (lcg * 48271) % 2147483647
    return (lcg / 2147483647) * span
end

local GCD_MS = math.floor((tonumber(CFG.gcd_s) or JOB.gcd_base_s) * 1000 + 0.5)
local LOCK_MS = JOB.anim_lock_s * 1000
local REQUEST_WINDOW_MS = JOB.gcd_request_window_s * 1000

sim = {
    heat = 0, battery = 0, gcdReadyAt = 0, gcdTotal = GCD_MS, lockUntil = 0,
    statuses = {}, targetStatuses = {}, overheatStacks = 0, lastCastAt = -999999, lastCastID = 0,
    comboStep = 0, comboUntil = 0, comboOK = true, queenBusyUntil = 0, queenActiveUntil = 0,
    wildfireHits = 0, pullAt = nil, potions = tonumber(CFG.potions) or 0, potionReadyAt = 0,
    log = {}, wildfires = {}, queens = {}, overdrives = {}, potionsUsed = {}, reassembled = {},
    brokenCombos = 0,
    wasted = { heat = 0, battery = 0 },
    idle = { gcd = 0, drillCapped = 0, AirAnchor = 0, ChainSaw = 0 },
    capped = { DoubleCheck = 0, Checkmate = 0, Reassemble = 0 },
    cd = {},
}

local enemies = math.max(1, tonumber(CFG.enemies) or 1)
local target = { id = 200, name = "Dummy", alive = true, targetable = true, incombat = true,
    attackable = true, distance2d = 10, los = true, hp = { current = 1e9, max = 1e9, percent = 100 },
    buffs = {}, pos = { x = 0, y = 0, z = 0 } }
local pack = { target }
for index = 2, enemies do
    pack[index] = { id = 200 + index, name = "Add " .. index, alive = true, targetable = true, incombat = true,
        attackable = true, distance2d = 10, los = true, hp = { current = 1e9, max = 1e9, percent = 100 },
        buffs = {}, pos = { x = 1, y = 0, z = 0 } }
end
EntityList = function() return pack end

Player = { id = 100, alive = true, job = JOB.job_id, incombat = CFG.start_in_combat ~= false,
    hp = { current = 1, percent = 100 }, buffs = {}, gauge = { 0, 0 },
    castinginfo = { lastcastid = 0, timesincecast = 999999 },
    GetTarget = function() return target end }

local function statusID(key) return STA[key].id end
local function has(key) return (sim.statuses[key] or 0) > clock end
local function grant(key, seconds) sim.statuses[key] = clock + seconds * 1000 end
local function strip(key) sim.statuses[key] = nil end

local keyByID = {}
for key, def in pairs(ACT) do
    if type(def) == "table" and def.id then
        keyByID[def.id] = key
        def.key = key
        def.group = def.group or key
        if def.recast_s and not sim.cd[def.group] then
            sim.cd[def.group] = { charges = def.charges or 1, max = def.charges or 1, recast = def.recast_s }
        end
    end
end
function actionName(id) return keyByID[id] or tostring(id) end

local function startCombat()
    if not Player.incombat then Player.incombat = true end
    if not sim.pullAt then sim.pullAt = clock end
end

-- Requirements beyond cooldown, lock and GCD. Out of combat only weaponskills
-- (which pull) and Reassemble are pressed; Barrel Stabilizer is in-combat only.
local function requirementMet(def)
    if not Player.incombat and not def.gcd and not def.out_of_combat then return false end
    if def.requires_status and not has(def.requires_status) then return false end
    local special = def.special
    if special == "overheated_weaponskill" then return has("Overheated") and sim.overheatStacks > 0 end
    if special == "hypercharge" then
        return not has("Overheated") and (sim.heat >= JOB.hypercharge_heat_cost or has("Hypercharged"))
    end
    if special == "queen" then return sim.battery >= JOB.queen.min_battery and clock >= sim.queenBusyUntil end
    if special == "overdrive" then return clock < sim.queenActiveUntil end
    return true
end

local function applySpecial(def)
    local special = def.special
    if special == "overheated_weaponskill" then
        sim.overheatStacks = sim.overheatStacks - 1
        if sim.overheatStacks <= 0 then strip("Overheated") end
    elseif special == "hypercharge" then
        if has("Hypercharged") then strip("Hypercharged") else sim.heat = sim.heat - JOB.hypercharge_heat_cost end
        grant("Overheated", STA.Overheated.duration_s)
        sim.overheatStacks = STA.Overheated.stacks
    elseif special == "wildfire" then
        grant("WildfireSelf", STA.WildfireSelf.duration_s)
        sim.wildfireHits = 0
        sim.wildfireOpenAt = clock
    elseif special == "queen" then
        table.insert(sim.queens, { t = clock / 1000, battery = sim.battery })
        sim.battery = 0
        sim.queenBusyUntil = clock + JOB.queen.lockout_s * 1000
        sim.queenActiveUntil = clock + 12000
    elseif special == "overdrive" then
        table.insert(sim.overdrives, { t = clock / 1000 })
        sim.queenActiveUntil = 0
    end
end

local objects = {}
local function makeAction(id)
    local key = keyByID[id]
    local def = key and ACT[key]
    local ac = { id = id, name = actionName(id), usable = def ~= nil, highlighted = false }
    if not def then
        ac.IsReady = function() return false end
        ac.Cast = function() return false end
        return ac
    end
    ac.refresh = function()
        local st = def.recast_s and sim.cd[def.group]
        if st then
            ac.recasttime = st.recast
            if st.charges >= st.max then
                ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
            else
                ac.cd, ac.cdmax, ac.isoncd = st.charges * st.recast, st.max * st.recast, true
            end
        else
            ac.recasttime = sim.gcdTotal / 1000
            local remaining = math.max(0, sim.gcdReadyAt - clock)
            if remaining <= 0 then
                ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
            else
                ac.cd, ac.cdmax, ac.isoncd = (sim.gcdTotal - remaining) / 1000, sim.gcdTotal / 1000, true
            end
        end
    end
    ac.IsReady = function(self, targetID)
        if def.self and targetID ~= Player.id then return false end
        if not def.self then
            local okTarget = false
            for _, entity in ipairs(pack) do if entity.id == targetID then okTarget = true end end
            if not okTarget then return false end
        end
        if clock < sim.lockUntil then return false end
        if def.gcd and sim.gcdReadyAt - clock > REQUEST_WINDOW_MS then return false end
        local st = def.recast_s and sim.cd[def.group]
        if st and st.charges < 1 then return false end
        return requirementMet(def)
    end
    ac.Cast = function(self, targetID)
        if not self:IsReady(targetID) then return false end
        local st = def.recast_s and sim.cd[def.group]
        if st then st.charges = st.charges - 1 end
        local entry = { t = clock / 1000, id = id, name = key, gcd = def.gcd == true, enemies = enemies,
            overheated = has("Overheated"), reassembled = false, combo = true }
        if def.gcd or (def.potency and not def.self) then startCombat() end
        if def.gcd then
            sim.gcdTotal = def.gcd_recast_s and def.gcd_recast_s * 1000 or GCD_MS
            sim.gcdReadyAt = math.max(clock, sim.gcdReadyAt) + sim.gcdTotal
            if has("WildfireSelf") then sim.wildfireHits = sim.wildfireHits + 1 end
            if has("Reassembled") and not def.keeps_reassemble then
                strip("Reassembled")
                entry.reassembled = true
                table.insert(sim.reassembled, key)
            end
            if def.combo_step then
                local continues = def.combo_step == 1 or
                    (sim.comboStep == def.combo_step - 1 and clock < sim.comboUntil)
                entry.combo = continues
                sim.comboOK = continues
                sim.comboStep = continues and def.combo_step % 3 or 0
                sim.comboUntil = clock + JOB.combo_window_s * 1000
                Player.lastcomboid = sim.comboStep > 0 and id or 0
                if not continues then sim.brokenCombos = sim.brokenCombos + 1 end
            elseif def.breaks_combo then
                sim.comboStep, Player.lastcomboid = 0, 0
            end
        end
        local gainHeat, gainBattery = def.heat or 0, def.battery or 0
        if def.combo_step and def.combo_step > 1 and not entry.combo then gainHeat, gainBattery = 0, 0 end
        sim.wasted.heat = sim.wasted.heat + math.max(0, sim.heat + gainHeat - JOB.heat_max)
        sim.wasted.battery = sim.wasted.battery + math.max(0, sim.battery + gainBattery - JOB.battery_max)
        sim.heat = math.min(JOB.heat_max, sim.heat + gainHeat)
        sim.battery = math.min(JOB.battery_max, sim.battery + gainBattery)
        if def.consumes_status then strip(def.consumes_status) end
        for _, g in ipairs(def.grants or {}) do grant(g.status, g.duration_s) end
        for group, seconds in pairs(def.refunds or {}) do
            local other = sim.cd[group]
            if other then other.charges = math.min(other.max, other.charges + seconds / other.recast) end
        end
        if def.dot then sim.targetStatuses[def.dot.status] = clock + def.dot.duration_s * 1000 end
        applySpecial(def)
        sim.lockUntil = clock + LOCK_MS + (tonumber(CFG.ping_ms) or 0) + jitter()
        sim.lastCastAt, sim.lastCastID = clock, id
        entry.heat, entry.battery = sim.heat, sim.battery
        table.insert(sim.log, entry)
        return true
    end
    return ac
end

ActionList = {
    Get = function(self, actionType, id)
        if not objects[id] then objects[id] = makeAction(id) end
        if objects[id].refresh then objects[id].refresh() end
        return objects[id]
    end,
    IsCasting = function() return false end,
}

-- The potion, reached through FFXIVMinion's GetItem(hqid, bags) helper.
local potionAction = { id = 9000049 }
local potion = { hqid = JOB.potion.hqid }
potion.IsReady = function(self) return sim.potions > 0 and clock >= sim.potionReadyAt and clock >= sim.lockUntil end
potion.GetAction = function(self) return potionAction end
potion.Cast = function(self, targetID)
    if not self:IsReady() then return false end
    sim.potions = sim.potions - 1
    sim.potionReadyAt = clock + JOB.potion.cooldown_s * 1000
    grant("Medicated", JOB.potion.duration_s)
    sim.lockUntil = clock + JOB.potion_anim_lock_s * 1000 + (tonumber(CFG.ping_ms) or 0)
    table.insert(sim.potionsUsed, { t = clock / 1000 })
    table.insert(sim.log, { t = clock / 1000, id = potionAction.id, name = "Potion", gcd = false, enemies = enemies,
        heat = sim.heat, battery = sim.battery, overheated = has("Overheated"), reassembled = false, combo = true })
    return true
end
GetItem = function(hqid, bags)
    if hqid ~= potion.hqid or sim.potions <= 0 then return nil, nil end
    local remaining = math.max(0, sim.potionReadyAt - clock) / 1000
    potionAction.isoncd = remaining > 0
    potionAction.cd, potionAction.cdmax = JOB.potion.cooldown_s - remaining, JOB.potion.cooldown_s
    return potion, potionAction
end

function advance(ms)
    local dt = ms / 1000
    if Player.incombat then
        if clock >= sim.gcdReadyAt and clock >= sim.lockUntil then sim.idle.gcd = sim.idle.gcd + dt end
        if sim.cd.Drill.charges >= sim.cd.Drill.max then sim.idle.drillCapped = sim.idle.drillCapped + dt end
        for _, key in ipairs({ "AirAnchor", "ChainSaw" }) do
            if sim.cd[key].charges >= 1 then sim.idle[key] = sim.idle[key] + dt end
        end
        for _, key in ipairs({ "DoubleCheck", "Checkmate", "Reassemble" }) do
            if sim.cd[key].charges >= sim.cd[key].max then sim.capped[key] = sim.capped[key] + dt end
        end
    end
    clock = clock + ms
    for _, st in pairs(sim.cd) do
        if st.charges < st.max then st.charges = math.min(st.max, st.charges + dt / st.recast) end
    end
    if sim.wildfireOpenAt and not has("WildfireSelf") then
        table.insert(sim.wildfires, { t = sim.wildfireOpenAt / 1000,
            hits = math.min(JOB.wildfire.max_hits, sim.wildfireHits) })
        sim.wildfireOpenAt = nil
    end
    if not has("Overheated") then sim.overheatStacks = 0 end

    Player.buffs = {}
    for key, untilAt in pairs(sim.statuses) do
        if untilAt > clock then
            table.insert(Player.buffs, { id = statusID(key), ownerid = Player.id, duration = (untilAt - clock) / 1000 })
        end
    end
    target.buffs = {}
    for key, untilAt in pairs(sim.targetStatuses) do
        if untilAt > clock then
            table.insert(target.buffs, { id = statusID(key), ownerid = Player.id, duration = (untilAt - clock) / 1000 })
        end
    end
    Player.gauge = { sim.heat, sim.battery }
    Player.combotimeremain = math.max(0, (sim.comboUntil - clock) / 1000)
    Player.castinginfo = { lastcastid = sim.lastCastID, timesincecast = clock - sim.lastCastAt }

    local kill = tonumber(CFG.kill_time_s)
    if kill and sim.pullAt then
        local percent = math.max(0, 100 * (1 - ((clock - sim.pullAt) / 1000) / kill))
        for _, entity in ipairs(pack) do
            entity.hp.percent, entity.hp.current = percent, percent * 1e7
        end
    end
end

-- Runs the engine until `seconds` of combat have passed (or the target dies).
function run(seconds)
    local pulse = tonumber(CFG.pulse_ms) or 30
    local kill = tonumber(CFG.kill_time_s)
    local limit = seconds
    if kill and kill < limit then limit = kill end
    local guard = clock + (seconds + 60) * 1000
    while clock < guard do
        if sim.pullAt and (clock - sim.pullAt) / 1000 >= limit then break end
        -- Someone else pulls: combat starts on its own after `pull_after_s`.
        if not sim.pullAt and tonumber(CFG.pull_after_s) and clock - CLOCK0 >= CFG.pull_after_s * 1000 then pull() end
        CielMachinistEngine.Step(true)
        advance(pulse)
    end
    sim.endedAt = clock / 1000
    sim.foughtFor = sim.pullAt and (clock - sim.pullAt) / 1000 or 0
end

function armPrepull(seconds) CielMachinistEngine.ArmPrepull(seconds) end
pull = startCombat
