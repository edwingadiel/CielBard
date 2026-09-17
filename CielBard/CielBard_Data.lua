CielBardData = CielBardData or {}

CielBardData.Version = "0.2.0"
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
}

CielBardData.Songs = {
    WM = { id = 3559, name = "The Wanderer's Minuet", next = "MB" },
    MB = { id = 114, name = "Mage's Ballad", next = "AP" },
    AP = { id = 116, name = "Army's Paeon", next = "WM" },
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

    autoTTK = true,
    manualTTK = 999,
    ttkSampleWindow = 8,
    minimumTTKConfidence = 0.50,
    terminalTTK = 20,
    idealKillMax = 30,

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

    -- MMOMinion exposes Player.gauge as an undocumented numeric array. These
    -- defaults match the conventional BRD layout but remain editable in-game.
    soulVoiceGaugeIndex = 4,
    repertoireGaugeIndex = 2,
    songTimerGaugeIndex = 3,

    debug = false,
}
