-- A time-stepped imitation of the MMOMinion client for a level-100 Dancer.
--
-- The shipped engine is driven pulse by pulse and every game rule that shapes
-- the rotation is enforced here: the GCD and its 1.0 s / 1.5 s dance variants,
-- animation lock, the random step sequences and the step gauge, the shared
-- Standard Step / Finishing Move recast, 50% procs, Fourfold Feathers, Esprit
-- from the dancer, the partner and the party, every Ready status, the combo,
-- the potion. There is no damage in this file: it produces a cast log with the
-- buffs that were up at each cast, and sim_dnc/core.py prices it afterwards.
-- Unlike Machinist, Dancer is random, so everything draws from one seeded
-- generator and a run is a pure function of (configuration, seed).
--
-- Inputs, published as globals before this file runs:
--   SIM_ACTIONS, SIM_STATUSES, SIM_JOB   the JSON tables under sim_dnc/data
--   SIM_CFG                              run configuration (see sim_dnc/core.py)
-- Load order: CielDancer_Data.lua, this file, CielDancer_Rotation.lua.

local ACT, STA, JOB, CFG = SIM_ACTIONS, SIM_STATUSES, SIM_JOB, SIM_CFG

-- The client clock does not start at zero: the engine rate-limits some work
-- (the inventory scan) against Now(), and a live client's tick count is large.
CLOCK0 = 100000
clock = CLOCK0 -- milliseconds
Now = function() return clock end
MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end

-- Park-Miller generator: Lua's math.random is seeded from the wall clock on
-- some builds, and every run has to be reproducible from its seed.
local lcg = ((tonumber(CFG.seed) or 1) * 2654435761) % 2147483647
if lcg == 0 then lcg = 1 end
local function random()
    lcg = (lcg * 48271) % 2147483647
    return lcg / 2147483647
end
for _ = 1, 8 do random() end

local GCD_MS = math.floor((tonumber(CFG.gcd_s) or JOB.gcd_base_s) * 1000 + 0.5)
local LOCK_MS = JOB.anim_lock_s * 1000
local REQUEST_WINDOW_MS = JOB.gcd_request_window_s * 1000

sim = {
    esprit = 0, feathers = 0, gcdReadyAt = 0, gcdTotal = GCD_MS, lockUntil = 0,
    statuses = {}, lastCastAt = -999999, lastCastID = 0,
    dance = nil, steps = { 0, 0, 0, 0 }, stepsDone = 0,
    standardMult = 1.0, technicalMult = 1.0,
    comboFrom = nil, comboUntil = 0, pullAt = nil,
    potions = tonumber(CFG.potions) or 0, potionReadyAt = 0, allyTickAt = 0,
    log = {}, potionsUsed = {},
    wasted = { esprit = 0, feathers = 0 },
    lapsed = {}, overwritten = {}, wrongSteps = 0, brokenCombos = 0,
    idle = { gcd = 0, StandardStep = 0, TechnicalStep = 0, Flourish = 0, Devilment = 0 },
    cd = {},
}

local enemies = math.max(1, tonumber(CFG.enemies) or 1)
local distance = tonumber(CFG.target_distance) or 3
local function makeEnemy(id, name)
    return { id = id, name = name, alive = true, targetable = true, incombat = true, attackable = true,
        distance2d = distance, los = true, hp = { current = 1e9, max = 1e9, percent = 100 },
        buffs = {}, pos = { x = distance, y = 0, z = 0 } }
end
local target = makeEnemy(200, "Dummy")
local pack = { target }
for index = 2, enemies do pack[index] = makeEnemy(200 + index, "Add " .. index) end
EntityList = function() return pack end

Player = { id = 100, alive = true, job = JOB.job_id, incombat = CFG.start_in_combat ~= false,
    hp = { current = 1, percent = 100 }, buffs = {}, gauge = { 0, 0, 0, 0, 0, 0, 0 },
    castinginfo = { lastcastid = 0, timesincecast = 999999 },
    GetTarget = function() return target end }

local function has(key) return (sim.statuses[key] or 0) > clock end
local function remaining(key) return math.max(0, ((sim.statuses[key] or 0) - clock) / 1000) end
local function grant(key, seconds)
    if has(key) and (key == "LastDanceReady" or key == "ThreefoldFanDance" or key == "FourfoldFanDance" or
        key == "SilkenSymmetry" or key == "SilkenFlow") then
        sim.overwritten[key] = (sim.overwritten[key] or 0) + 1
    end
    sim.statuses[key] = clock + seconds * 1000
end
local function strip(key) sim.statuses[key] = nil end

local keyByID = {}
for key, def in pairs(ACT) do
    if type(def) == "table" and def.id then
        keyByID[def.id] = key
        def.key = key
        if def.recast_s then
            def.group = def.group or key
            if not sim.cd[def.group] then sim.cd[def.group] = { readyAt = 0, recast = def.recast_s } end
        end
    end
end
function actionName(id) return keyByID[id] or tostring(id) end

local function startCombat()
    if not Player.incombat then Player.incombat = true end
    if not sim.pullAt then
        sim.pullAt = clock
        sim.allyTickAt = clock
    end
end

local function gainEsprit(amount)
    sim.wasted.esprit = sim.wasted.esprit + math.max(0, sim.esprit + amount - JOB.esprit_max)
    sim.esprit = math.min(JOB.esprit_max, sim.esprit + amount)
end

local function gainFeather()
    if sim.feathers >= JOB.feather_max then
        sim.wasted.feathers = sim.wasted.feathers + 1
    else
        sim.feathers = sim.feathers + 1
    end
end

local function espritStatusUp() return has("EspritStandard") or has("EspritTechnical") end

-- A random sequence of `count` distinct steps.
local function rollSteps(count)
    local pool = { 1, 2, 3, 4 }
    local out = { 0, 0, 0, 0 }
    for index = 1, count do
        local pick = math.floor(random() * #pool) + 1
        out[index] = table.remove(pool, pick)
    end
    return out
end

local function availableStatus(list)
    for _, key in ipairs(list or {}) do
        if has(key) then return key end
    end
    return nil
end

-- Requirements beyond cooldown, lock and GCD.
local function requirementMet(def)
    local special = def.special
    if sim.dance then
        -- While dancing only the steps and the matching finish can be pressed.
        if special == "step" then return true end
        if special == "standard_finish" then return sim.dance == "STANDARD" and def.steps == sim.stepsDone end
        if special == "technical_finish" then return sim.dance == "TECHNICAL" and def.steps == sim.stepsDone end
        return false
    end
    if special == "step" or special == "standard_finish" or special == "technical_finish" then return false end
    if not Player.incombat and not def.out_of_combat and not (def.gcd and def.potency) then return false end
    if special == "standard_step" and has("FinishingMoveReady") then return false end -- the button is Finishing Move
    if def.requires_any and not availableStatus(def.requires_any) then return false end
    if def.esprit_cost and sim.esprit < def.esprit_cost then return false end
    if special == "saber_dance" and has("DanceOfTheDawnReady") then return false end -- the button is Dance of the Dawn
    if def.feather_cost and sim.feathers < def.feather_cost then return false end
    return true
end

local function applySpecial(def, entry)
    local special = def.special
    if special == "standard_step" or special == "technical_step" then
        sim.dance = special == "standard_step" and "STANDARD" or "TECHNICAL"
        sim.steps = rollSteps(sim.dance == "STANDARD" and 2 or 4)
        sim.stepsDone = 0
        grant(sim.dance == "STANDARD" and "StandardStep" or "TechnicalStep", JOB.dance_window_s)
    elseif special == "step" then
        if sim.steps[sim.stepsDone + 1] == def.step then
            sim.stepsDone = sim.stepsDone + 1
        else
            sim.wrongSteps = sim.wrongSteps + 1
            entry.wrong = true
        end
    elseif special == "standard_finish" or special == "finishing_move" then
        local rule = JOB.standard_finish
        local steps = special == "finishing_move" and 2 or def.steps
        if steps > 0 then
            sim.standardMult = rule.damage_mult_by_steps[steps + 1]
            grant("StandardFinish", rule.duration_s)
            grant("EspritStandard", rule.esprit_status_s)
        end
        grant("LastDanceReady", rule.last_dance_ready_s)
        if special == "standard_finish" then
            sim.dance, sim.stepsDone, sim.steps = nil, 0, { 0, 0, 0, 0 }
            strip("StandardStep")
        end
    elseif special == "technical_finish" then
        local rule = JOB.technical_finish
        if def.steps > 0 then
            sim.technicalMult = rule.damage_mult_by_steps[def.steps + 1]
            grant("TechnicalFinish", rule.duration_s)
            grant("EspritTechnical", rule.esprit_status_s)
        end
        grant("FlourishingFinish", rule.flourishing_finish_s)
        grant("DanceOfTheDawnReady", rule.dance_of_the_dawn_ready_s)
        sim.dance, sim.stepsDone, sim.steps = nil, 0, { 0, 0, 0, 0 }
        strip("TechnicalStep")
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
        local ownRemaining = st and math.max(0, st.readyAt - clock) or 0
        local gcdRemaining = def.gcd and math.max(0, sim.gcdReadyAt - clock) or 0
        if st and ownRemaining >= gcdRemaining and ownRemaining > 0 then
            ac.recasttime = st.recast
            ac.cd, ac.cdmax, ac.isoncd = st.recast - ownRemaining / 1000, st.recast, true
        elseif gcdRemaining > 0 then
            ac.recasttime = sim.gcdTotal / 1000
            ac.cd, ac.cdmax, ac.isoncd = (sim.gcdTotal - gcdRemaining) / 1000, sim.gcdTotal / 1000, true
        else
            ac.recasttime = st and st.recast or sim.gcdTotal / 1000
            ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
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
        if st and st.readyAt > clock then return false end
        return requirementMet(def)
    end
    ac.Cast = function(self, targetID)
        if not self:IsReady(targetID) then return false end
        local st = def.recast_s and sim.cd[def.group]
        if st then st.readyAt = clock + st.recast * 1000 end
        local entry = { t = clock / 1000, id = id, name = key, gcd = def.gcd == true, enemies = enemies,
            combo = true, standard = has("StandardFinish") and sim.standardMult or 1.0,
            technical = has("TechnicalFinish") and sim.technicalMult or 1.0,
            devilment = has("Devilment"), medicated = has("Medicated") }
        if def.potency then startCombat() end
        if def.gcd then
            sim.gcdTotal = def.gcd_recast_s and def.gcd_recast_s * 1000 or GCD_MS
            sim.gcdReadyAt = math.max(clock, sim.gcdReadyAt) + sim.gcdTotal
            if def.combo_start then
                sim.comboFrom, sim.comboUntil = key, clock + JOB.combo_window_s * 1000
                Player.lastcomboid = id
            elseif def.combo_from then
                entry.combo = sim.comboFrom == def.combo_from and clock < sim.comboUntil
                if not entry.combo then sim.brokenCombos = sim.brokenCombos + 1 end
                sim.comboFrom, Player.lastcomboid = nil, 0
            end
        end
        local consumed = availableStatus(def.requires_any)
        if consumed then strip(consumed) end
        if def.esprit_cost then sim.esprit = sim.esprit - def.esprit_cost end
        if def.feather_cost then sim.feathers = sim.feathers - def.feather_cost end
        if def.esprit and (def.esprit_unconditional or espritStatusUp()) then gainEsprit(def.esprit) end
        if def.feather_chance and random() < def.feather_chance then gainFeather() end
        if def.proc and random() < def.proc.chance then grant(def.proc.status, def.proc.duration_s) end
        if def.combo_proc and entry.combo and random() < def.combo_proc.chance then
            grant(def.combo_proc.status, def.combo_proc.duration_s)
        end
        for _, g in ipairs(def.grants or {}) do grant(g.status, g.duration_s) end
        -- The entry records the buffs before this cast's own effects: a finish
        -- does not benefit from the buff it applies.
        applySpecial(def, entry)
        sim.lockUntil = clock + LOCK_MS + (tonumber(CFG.ping_ms) or 0)
        sim.lastCastAt, sim.lastCastID = clock, id
        entry.esprit, entry.feathers = sim.esprit, sim.feathers
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
potion.IsReady = function(self)
    return sim.potions > 0 and clock >= sim.potionReadyAt and clock >= sim.lockUntil
end
potion.GetAction = function(self) return potionAction end
potion.Cast = function(self, targetID)
    if not self:IsReady() then return false end
    sim.potions = sim.potions - 1
    sim.potionReadyAt = clock + JOB.potion.cooldown_s * 1000
    grant("Medicated", JOB.potion.duration_s)
    sim.lockUntil = clock + JOB.potion_anim_lock_s * 1000 + (tonumber(CFG.ping_ms) or 0)
    table.insert(sim.potionsUsed, { t = clock / 1000 })
    table.insert(sim.log, { t = clock / 1000, id = potionAction.id, name = "Potion", gcd = false, enemies = enemies,
        combo = true, standard = 1.0, technical = 1.0, devilment = false, medicated = false,
        esprit = sim.esprit, feathers = sim.feathers })
    return true
end
GetItem = function(hqid, bags)
    if hqid ~= potion.hqid or sim.potions <= 0 then return nil, nil end
    local left = math.max(0, sim.potionReadyAt - clock) / 1000
    potionAction.isoncd = left > 0
    potionAction.cd, potionAction.cdmax = JOB.potion.cooldown_s - left, JOB.potion.cooldown_s
    return potion, potionAction
end

-- Allies. The partner generates Esprit while the Standard Esprit status is
-- up, the rest of the party while the Technical one is.
local function allyEsprit()
    local rule = JOB.ally_esprit
    local chance = tonumber(CFG.ally_esprit_chance) or rule.chance
    local sources = 0
    if CFG.partner ~= false and (has("EspritStandard") or has("EspritTechnical")) then sources = sources + 1 end
    if has("EspritTechnical") then sources = sources + math.max(0, (tonumber(CFG.party_size) or 8) - 2) end
    for _ = 1, sources do
        if random() < chance then gainEsprit(rule.amount) end
    end
end

local LAPSE_WATCH = { "SilkenSymmetry", "SilkenFlow", "FlourishingSymmetry", "FlourishingFlow", "ThreefoldFanDance",
    "FourfoldFanDance", "LastDanceReady", "FinishingMoveReady", "DanceOfTheDawnReady", "FlourishingFinish",
    "FlourishingStarfall" }

function advance(ms)
    local dt = ms / 1000
    if Player.incombat then
        if clock >= sim.gcdReadyAt and clock >= sim.lockUntil then sim.idle.gcd = sim.idle.gcd + dt end
        if not sim.dance then
            for _, key in ipairs({ "StandardStep", "TechnicalStep", "Flourish", "Devilment" }) do
                if sim.cd[key].readyAt <= clock then sim.idle[key] = sim.idle[key] + dt end
            end
        end
    end
    clock = clock + ms
    for _, key in ipairs(LAPSE_WATCH) do
        local untilAt = sim.statuses[key]
        if untilAt and untilAt <= clock then
            sim.lapsed[key] = (sim.lapsed[key] or 0) + 1
            sim.statuses[key] = nil
        end
    end
    if sim.dance and not has(sim.dance == "STANDARD" and "StandardStep" or "TechnicalStep") then
        sim.lapsed.Dance = (sim.lapsed.Dance or 0) + 1
        sim.dance, sim.stepsDone, sim.steps = nil, 0, { 0, 0, 0, 0 }
    end
    if sim.pullAt and CFG.party ~= false then
        while clock - sim.allyTickAt >= JOB.ally_esprit.ally_gcd_s * 1000 do
            sim.allyTickAt = sim.allyTickAt + JOB.ally_esprit.ally_gcd_s * 1000
            allyEsprit()
        end
    end

    Player.buffs = {}
    for key, untilAt in pairs(sim.statuses) do
        if untilAt > clock and STA[key] then
            table.insert(Player.buffs, { id = STA[key].id, ownerid = Player.id, duration = (untilAt - clock) / 1000 })
        end
    end
    Player.gauge = { sim.feathers, sim.esprit, sim.steps[1], sim.steps[2], sim.steps[3], sim.steps[4], sim.stepsDone }
    Player.combotimeremain = sim.comboFrom and math.max(0, (sim.comboUntil - clock) / 1000) or 0
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
        if not sim.pullAt and tonumber(CFG.pull_after_s) and clock - CLOCK0 >= CFG.pull_after_s * 1000 then
            startCombat()
        end
        CielDancerEngine.Step(true)
        advance(pulse)
    end
    sim.endedAt = clock / 1000
    sim.foughtFor = sim.pullAt and (clock - sim.pullAt) / 1000 or 0
end

function armPrepull(seconds) CielDancerEngine.ArmPrepull(seconds) end
