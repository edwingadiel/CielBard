CielBardData = CielBardData or {}

CielBardData.Version = "0.3.0"
CielBardData.BardJobID = 23

-- FFXIV action IDs. ActionList resolves availability, level sync, transformed
-- actions, cooldowns, and proc requirements at runtime.
CielBardData.Actions = {
    HeavyShot = 97,
    VenomousBite = 100,
    RagingStrikes = 101,
    QuickNock = 106,
    Barrage = 107,
    Bloodletter = 110,
    Windbite = 113,
    MagesBallad = 114,
    ArmysPaeon = 116,
    RainOfDeath = 117,
    BattleVoice = 118,

    EmpyrealArrow = 3558,
    WanderersMinuet = 3559,
    IronJaws = 3560,
    Sidewinder = 3562,
    PitchPerfect = 7404,
    CausticBite = 7406,
    Stormbite = 7407,
    RefulgentArrow = 7409,

    Shadowbite = 16494,
    BurstShot = 16495,
    ApexArrow = 16496,

    Ladonsbite = 25783,
    BlastArrow = 25784,
    RadiantFinale = 25785,

    SecondWind = 7541,
    Troubadour = 7405,
    NaturesMinne = 7408,
    WardensPaean = 3561,

    HeartbreakShot = 36975,
    ResonantArrow = 36976,
    RadiantEncore = 36977,
}

-- Current Dawntrail DoT status IDs. The engine also verifies ownership, so
-- another Bard's DoTs never satisfy our maintenance checks.
CielBardData.Statuses = {
    VenomousBite = 124,
    Windbite = 129,
    CausticBite = 1200,
    Stormbite = 1201,
}

CielBardData.GCD = {
    [97] = true, [100] = true, [106] = true,
    [3560] = true, [7406] = true, [7407] = true, [7409] = true,
    [16494] = true, [16495] = true, [16496] = true,
    [25783] = true, [25784] = true,
    [36976] = true, [36977] = true,
}

CielBardData.SelfTarget = {
    [101] = true, [107] = true, [118] = true, [25785] = true,
    [7541] = true, [7405] = true, [7408] = true, [3561] = true,
}

CielBardData.Songs = {
    WM = { id = 3559, name = "The Wanderer's Minuet", next = "MB" },
    MB = { id = 114, name = "Mage's Ballad", next = "AP" },
    AP = { id = 116, name = "Army's Paeon", next = "WM" },
}

-- Every optional action is routed through this central capability table. The
-- optimized defaults preserve the v0.2 behavior; utility automation is opt-in.
CielBardData.AbilityDefaults = {
    WanderersMinuet = true,
    MagesBallad = true,
    ArmysPaeon = true,

    Stormbite = true,
    CausticBite = true,
    IronJaws = true,

    RagingStrikes = true,
    BattleVoice = true,
    RadiantFinale = true,
    Barrage = true,

    RefulgentArrow = true,
    ApexArrow = true,
    BlastArrow = true,
    PitchPerfect = true,
    ResonantArrow = true,
    RadiantEncore = true,

    EmpyrealArrow = true,
    Sidewinder = true,
    HeartbreakShot = true,
    Bloodletter = true,
    RainOfDeath = true,

    Ladonsbite = true,
    Shadowbite = true,

    SecondWind = false,
    Troubadour = false,
    NaturesMinne = false,
    WardensPaean = false,
}

CielBardData.Defaults = {
    enabled = false,
    showWindow = true,
    useAOE = true,
    minAOETargets = 2,
    requireCombat = true,
    pulseMs = 60,
    requestThrottleMs = 125,
    maxWeaves = 2,
    executionMode = "FULL", -- FULL, GCD_ONLY, or OGCD_ONLY
    requireLOS = true,

    -- Normal users can ignore this switch and receive the optimized defaults.
    -- Per-ability controls and alternate presets only apply when it is enabled.
    advancedEnabled = false,
    preset = "Optimized",
    abilities = CielBardData.AbilityDefaults,
    automaticSongCycle = true,

    autoTTK = true,
    manualTTK = 999,
    ttkSampleWindow = 8,
    minimumTTKConfidence = 0.50,
    terminalTTK = 20,
    idealKillMax = 30,
    terminalDumping = true,
    resourcePooling = true,

    dotRefreshSeconds = 3.0,
    dotMinimumTTK = 18,
    snapshotIronJaws = true,

    -- Empirical top-10 transition timings from the Vamp Fatale study.
    -- Songs last 45 seconds, so these are remaining-time thresholds.
    wmSwapRemaining = 1.2,
    mbSwapRemaining = 2.7,
    apSwapRemaining = 10.1,

    apexBurstGauge = 80,
    apexOffcycleGauge = 90,
    apexHoldForBurstSeconds = 35,

    secondWindHP = 45,
    minneHP = 60,
    troubadourHP = 70,

    -- MMOMinion exposes Player.gauge as an undocumented numeric array. These
    -- defaults match the conventional BRD layout but remain editable in-game.
    soulVoiceGaugeIndex = 4,
    repertoireGaugeIndex = 2,
    songTimerGaugeIndex = 3,

    debug = false,
}

-- Presets are deliberately small overrides applied on top of the optimized
-- defaults. "Custom" is selected automatically after a manual change.
CielBardData.Presets = {
    Optimized = {},
    Conservative = {
        maxWeaves = 1,
        snapshotIronJaws = false,
        terminalDumping = false,
        resourcePooling = false,
    },
    NoPartyBuffs = {
        abilities = { BattleVoice = false, RadiantFinale = false },
    },
    NoDots = {
        snapshotIronJaws = false,
        abilities = { Stormbite = false, CausticBite = false, IronJaws = false },
    },
    SingleTarget = {
        useAOE = false,
        abilities = { RainOfDeath = false, Ladonsbite = false, Shadowbite = false },
    },
    GCDOnly = {
        executionMode = "GCD_ONLY",
    },
}
