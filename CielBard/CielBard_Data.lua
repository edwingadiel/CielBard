CielBardData = CielBardData or {}

CielBardData.Version = "0.4.0"
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

-- Dexterity potions in preference order (newest grade first). MMOMinion
-- addresses HQ items as id + 1000000; the engine tries HQ before NQ.
CielBardData.Potions = {
    { id = 49235, name = "Grade 4 Gemdraught of Dexterity" },
    { id = 45996, name = "Grade 3 Gemdraught of Dexterity" },
    { id = 44163, name = "Grade 2 Gemdraught of Dexterity" },
    { id = 44158, name = "Grade 1 Gemdraught of Dexterity" },
}
CielBardData.HQOffset = 1000000

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

-- Per-action nearby-target thresholds for AoE replacements. With current
-- potencies every replacement is a gain at two targets:
--   Ladonsbite 140/target vs Burst Shot 220, Shadowbite 200/target vs
--   Refulgent 280, Rain of Death 100/target vs Heartbreak Shot 180.
-- They stay separately tunable because radius and positioning differ.
CielBardData.AoEDefaults = {
    Ladonsbite = 2,
    Shadowbite = 2,
    RainOfDeath = 2,
}

CielBardData.Defaults = {
    enabled = false,
    showWindow = true,
    useAOE = true,
    aoeTargets = CielBardData.AoEDefaults,
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

    -- Multi-dotting: keep both DoTs on additional engaged enemies that will
    -- live long enough to pay back the application GCD. Secondary targets are
    -- cast on directly; the player's current target is left alone.
    multiDot = true,
    multiDotMaxTargets = 3,
    multiDotMinHPPercent = 30,

    -- How much DoT coverage a two-minute burst waits for before Raging
    -- Strikes: NONE, ONE (at least one enabled DoT active), or BOTH.
    -- ONE matches the standard opener where Raging follows the first DoT.
    burstDotGate = "ONE",

    -- Radiant Finale scales with tracked codas (2/4/6%). It is never
    -- requested at zero codas, and a song that is about to be cast anyway is
    -- allowed to land first when it would add a coda. Holding beyond one coda
    -- risks losing a use, so the minimum stays at 1 unless the user raises it.
    radiantFinaleMinCodas = 1,
    radiantFinaleCodaHold = 2.0,

    -- Potion use is opt-in because it consumes inventory. When enabled the
    -- engine weaves the best available Gemdraught of Dexterity immediately
    -- before Raging Strikes so the 30s effect covers the whole buff window.
    usePotion = false,
    potionOnlyWithBurst = true,
    potionHQOnly = false,
    potionMinimumTTK = 8,

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
        multiDot = false,
        burstDotGate = "BOTH",
    },
    NoPartyBuffs = {
        abilities = { BattleVoice = false, RadiantFinale = false },
    },
    NoDots = {
        snapshotIronJaws = false,
        multiDot = false,
        abilities = { Stormbite = false, CausticBite = false, IronJaws = false },
    },
    SingleTarget = {
        useAOE = false,
        multiDot = false,
        abilities = { RainOfDeath = false, Ladonsbite = false, Shadowbite = false },
    },
    GCDOnly = {
        executionMode = "GCD_ONLY",
    },
}
