CielMachinistData = CielMachinistData or {}

CielMachinistData.Version = "0.2.0"
CielMachinistData.MachinistJobID = 31
CielMachinistData.ACRProfileName = "CielMachinist"

-- FFXIV action IDs. ActionList resolves availability, level sync, transformed
-- actions, cooldowns, and proc requirements at runtime. Upgraded actions are
-- requested first and their base versions are kept as level-sync fallbacks.
CielMachinistData.Actions = {
    SplitShot = 2866,
    SlugShot = 2868,
    SpreadShot = 2870,
    HotShot = 2872,
    CleanShot = 2873,
    GaussRound = 2874,
    Reassemble = 2876,
    Wildfire = 2878,
    Dismantle = 2887,
    Ricochet = 2890,
    RookAutoturret = 2864,

    HeatBlast = 7410,
    HeatedSplitShot = 7411,
    HeatedSlugShot = 7412,
    HeatedCleanShot = 7413,
    BarrelStabilizer = 7414,
    RookOverdrive = 7415,

    AutoCrossbow = 16497,
    Drill = 16498,
    Bioblaster = 16499,
    AirAnchor = 16500,
    AutomatonQueen = 16501,
    QueenOverdrive = 16502,
    Tactician = 16889,
    Hypercharge = 17209,

    Scattergun = 25786,
    ChainSaw = 25788,

    BlazingShot = 36978,
    DoubleCheck = 36979,
    Checkmate = 36980,
    Excavator = 36981,
    FullMetalField = 36982,

    SecondWind = 7541,
}

CielMachinistData.Statuses = {
    Reassembled = 851,
    Overheated = 2688,
    Hypercharged = 3864,
    ExcavatorReady = 3865,
    FullMetalMachinist = 3866,
    WildfireSelf = 1946,
    Bioblaster = 1866,
}

-- Dexterity potions in preference order (newest grade first). MMOMinion
-- addresses HQ items as id + 1000000; the engine tries HQ before NQ.
CielMachinistData.Potions = {
    { id = 49235, name = "Grade 4 Gemdraught of Dexterity" },
    { id = 45996, name = "Grade 3 Gemdraught of Dexterity" },
    { id = 44163, name = "Grade 2 Gemdraught of Dexterity" },
    { id = 44158, name = "Grade 1 Gemdraught of Dexterity" },
}
CielMachinistData.HQOffset = 1000000

-- Every weaponskill, upgraded and base. Used for weave counting, the
-- pending-request tier hold, and Wildfire/Reassemble bookkeeping.
CielMachinistData.GCD = {
    [2866] = true, [2868] = true, [2873] = true,
    [7411] = true, [7412] = true, [7413] = true,
    [2870] = true, [25786] = true,
    [2872] = true, [16500] = true,
    [16498] = true, [16499] = true,
    [25788] = true, [36981] = true, [36982] = true,
    [7410] = true, [36978] = true, [16497] = true,
}

-- Actions that must be requested on the player. Live clients report
-- IsReady=false for these when asked about an enemy target.
CielMachinistData.SelfTarget = {
    [2876] = true, -- Reassemble
    [7414] = true, -- Barrel Stabilizer
    [17209] = true, -- Hypercharge
    [2864] = true, [16501] = true, -- Rook Autoturret, Automaton Queen
    [7415] = true, [16502] = true, -- Rook Overdrive, Queen Overdrive
    [16889] = true, -- Tactician
    [7541] = true, -- Second Wind
}

-- Combo chain. Each step lists every id the client may report for it so a
-- level-synced Split Shot still advances the tracker.
CielMachinistData.Combo = {
    { key = "HeatedSplitShot", ids = { 7411, 2866 } },
    { key = "HeatedSlugShot", ids = { 7412, 2868 } },
    { key = "HeatedCleanShot", ids = { 7413, 2873 } },
}
CielMachinistData.ComboWindowSeconds = 30

-- Every optional action is routed through this central capability table.
-- Utility automation is opt-in.
CielMachinistData.AbilityDefaults = {
    Drill = true,
    AirAnchor = true,
    ChainSaw = true,
    Excavator = true,
    FullMetalField = true,

    Hypercharge = true,
    BlazingShot = true,
    Wildfire = true,
    BarrelStabilizer = true,
    Reassemble = true,

    DoubleCheck = true,
    Checkmate = true,
    AutomatonQueen = true,
    QueenOverdrive = true,

    Scattergun = true,
    AutoCrossbow = true,
    Bioblaster = true,

    SecondWind = false,
    Tactician = false,
}

-- Per-action nearby-target thresholds for AoE replacements (The Balance):
--   Scattergun 130/target vs the ~320 average combo GCD -> 3.
--   Bioblaster 50 + 50 x 5 ticks per target vs Drill 660 -> 3.
--   Auto Crossbow 180/target vs Blazing Shot 240 looks like a gain at two, but
--     only Blazing Shot refunds 15 s to Double Check and Checkmate (180 each,
--     cleaving), so Auto Crossbow does not win until six clustered targets.
CielMachinistData.AoEDefaults = {
    Scattergun = 3,
    AutoCrossbow = 6,
    Bioblaster = 3,
}

-- Overheated lasts five weaponskills at a 1.5 s recast.
CielMachinistData.OverheatedWindowSeconds = 10
CielMachinistData.WildfireWindowSeconds = 10

CielMachinistData.Defaults = {
    enabled = false,
    showWindow = true,
    useAOE = true,
    aoeTargets = CielMachinistData.AoEDefaults,
    requireCombat = true,
    pulseMs = 30,
    requestThrottleMs = 60,
    -- An accepted request is held for this long so a live client that keeps
    -- reporting the action ready cannot make the engine send the same cast
    -- twice. Cleared early by an observed cast or the action going on cooldown.
    requestDedupeMs = 350,
    settingsVersion = 1,
    lockToolNoticeDismissed = false,
    maxWeaves = 2,
    -- Overheated weaponskills recast in 1.5 s: exactly one weave fits.
    maxWeavesOverheated = 1,
    -- GCD is treated as ready this many seconds early so requests queue
    -- without a gap; oGCDs are only weaved when at least this much GCD remains.
    gcdLeadSeconds = 0.05,
    weaveMinGcdRemaining = 0.65,
    executionMode = "FULL", -- FULL, GCD_ONLY, or OGCD_ONLY
    requireLOS = false, -- opt-in: live clients report los=false on dummies in plain view

    -- Normal users can ignore this switch and receive the optimized defaults.
    -- Per-ability controls and alternate presets only apply when it is enabled.
    advancedEnabled = false,
    preset = "Optimized",
    abilities = CielMachinistData.AbilityDefaults,

    autoTTK = true,
    manualTTK = 999,
    ttkSampleWindow = 8,
    minimumTTKConfidence = 0.50,
    terminalTTK = 20,
    idealKillMax = 30,
    terminalDumping = true,
    resourcePooling = true,

    -- Hypercharge is refused while any enabled tool would come off cooldown
    -- inside the Overheated window (five 1.5 s weaponskills plus the queue).
    hyperchargeToolLeadSeconds = 8.0,
    -- The GCD is held this long for Air Anchor or Chain Saw rather than
    -- pressing a filler that would drift the tool by a whole GCD.
    toolHoldSeconds = 0.4,
    -- A heat-funded Hypercharge is not started this close to the two-minute
    -- burst, so Overheated never overlaps Barrel Stabilizer and Wildfire.
    hyperchargeHoldForBurstSeconds = 12,
    -- Heat kept at the top of the burst so a second, heat-funded Hypercharge
    -- can follow the free one, as in The Balance's static burst. OFF (0) by
    -- default: sim_mch measures it at -0.07% to -0.24% on average across fight
    -- lengths and party-buff placements, because the second Hypercharge lands
    -- after the 20 s window anyway and banked heat is heat not yet spent.
    -- 45 is the value to try. `heatPerSecond` is the regeneration it assumes.
    hyperchargeBurstHeat = 0,
    heatPerSecond = 1.0,
    -- Wildfire follows Hypercharge directly. It is not spent on an Overheated
    -- window with fewer than this many Blazing Shots left.
    wildfireMinimumStacks = 3,
    wildfireMinimumTTK = 8,

    -- Automaton Queen. Her potency is linear in the battery spent, so the
    -- only losses are overcapping and arriving at the burst without a full
    -- battery. Off-cycle she is summoned near the cap. The battery refills at
    -- roughly 1.9 per second, so inside the refill window before a burst it is
    -- kept (unless already full), and just ahead of that window she takes
    -- whatever is banked: the last call. The burst Queen then goes out at 100
    -- once Air Anchor has topped her off, as in The Balance's schedule.
    queenBatteryOffcycle = 90,
    queenBatteryBurst = 50,
    queenRefillSeconds = 42,
    queenLastCallSeconds = 10,
    queenTopOffSeconds = 5.5, -- in burst, wait for a +20 battery tool due within two GCDs
    queenMinimumTTK = 10,
    queenOverdriveTTK = 5,

    -- Double Check / Checkmate: three charges each on a 30 s recharge, and
    -- every Blazing Shot refunds 15 s to both. Outside burst they are spent
    -- down to this many banked charges when the burst is close.
    chargePoolSeconds = 15,
    chargeCapLeadSeconds = 4.0,

    -- Reassemble: spent on the next tool unless that would leave fewer than
    -- this many charges when the burst arrives. Inside the burst an uncapped
    -- charge waits a few seconds so it lands under party buffs.
    reassembleBurstCharges = 1,
    reassembleBurstDelaySeconds = 6,

    -- Potion use is opt-in because it consumes inventory.
    usePotion = false,
    potionOnlyWithBurst = true,
    potionHQOnly = false,
    potionMinimumTTK = 8,
    potionPrepull = true, -- with potion use on, the pre-pull takes it too

    -- Pre-pull Reassemble (and potion): automatic when the engine pulls
    -- (requireCombat off), otherwise armed from the window.
    prepull = true,

    secondWindHP = 45,
    tacticianHP = 70,

    -- MMOMinion exposes Player.gauge as an undocumented numeric array. The
    -- bundled FFXIVMinion Machinist profile reads Heat from slot 1 and Battery
    -- from slot 2; both remain editable in-game.
    heatGaugeIndex = 1,
    batteryGaugeIndex = 2,

    debug = false,
}

-- Presets are deliberately small overrides applied on top of the optimized
-- defaults. "Custom" is selected automatically after a manual change.
CielMachinistData.Presets = {
    Optimized = {},
    Conservative = {
        maxWeaves = 1,
        terminalDumping = false,
        resourcePooling = false,
    },
    NoQueen = {
        abilities = { AutomatonQueen = false, QueenOverdrive = false },
    },
    SingleTarget = {
        useAOE = false,
        abilities = { Scattergun = false, AutoCrossbow = false, Bioblaster = false },
    },
    GCDOnly = {
        executionMode = "GCD_ONLY",
    },
}
