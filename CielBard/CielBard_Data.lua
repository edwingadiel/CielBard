CielBardData = CielBardData or {}

CielBardData.Version = "0.5.2"
CielBardData.BardJobID = 23
CielBardData.ACRProfileName = "CielBard"

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
    [97] = true, [100] = true, [106] = true, [113] = true,
    [3560] = true, [7406] = true, [7407] = true, [7409] = true,
    [16494] = true, [16495] = true, [16496] = true,
    [25783] = true, [25784] = true,
    [36976] = true, [36977] = true,
}

-- Actions that must be requested on the player. Live clients report
-- IsReady=false for these when asked about an enemy target (songs included).
CielBardData.SelfTarget = {
    [101] = true, [107] = true, [118] = true, [25785] = true,
    [7541] = true, [7405] = true, [7408] = true, [3561] = true,
    [3559] = true, [114] = true, [116] = true, -- Wanderer's Minuet, Mage's Ballad, Army's Paeon
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
--
-- ShadowbiteBarrage is the separate threshold used while Barrage is active
-- (v0.5.2, review 0.5.1 High #2). Barrage makes Refulgent Arrow strike three
-- times (280 x 3 = 840) but only raises Shadowbite's potency to 300 per
-- target, so Shadowbite needs three targets to win under Barrage:
--   2 targets: Barrage-Shadowbite 600 vs Barrage-Refulgent 840 -> Refulgent.
--   3 targets: Barrage-Shadowbite 900 vs Barrage-Refulgent 840 -> Shadowbite.
CielBardData.AoEDefaults = {
    Ladonsbite = 2,
    Shadowbite = 2,
    ShadowbiteBarrage = 3,
    RainOfDeath = 2,
}

-- Barrage's buff window. Used as the fallback lifetime of a locally tracked
-- Barrage when the client does not expose the action's statusgainedid.
CielBardData.BarrageWindowSeconds = 10

CielBardData.Defaults = {
    enabled = false,
    showWindow = true,
    useAOE = true,
    aoeTargets = CielBardData.AoEDefaults,
    requireCombat = true,
    pulseMs = 30,
    requestThrottleMs = 60,
    -- Pending-request dedupe (review 0.5.1, medium): an accepted request is
    -- held for this long so a live client that keeps reporting the action
    -- ready cannot make the engine send the same cast twice. Cleared early by
    -- an observed cast or by the client reporting the action on cooldown.
    requestDedupeMs = 350,
    timingVersion = 4,
    lockToolNoticeDismissed = false,
    maxWeaves = 2,
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
    dotUrgentSeconds = 1.5, -- Iron Jaws pre-empts proc GCDs when a DoT is this close to falling off
    dotMinimumTTK = 18,
    snapshotIronJaws = true,

    -- Multi-dotting: keep both DoTs on additional engaged enemies that will
    -- live long enough to pay back the application GCD. Secondary targets are
    -- cast on directly; the player's current target is left alone.
    --
    -- Default OFF since v0.5.2 (review 0.5.1, High #3): eligibility is still
    -- an HP-percent floor plus the primary target's TTK, with no per-target
    -- TTK estimate and no potency-payback calculation, so on ordinary trash
    -- packs the engine can spend several GCDs dotting adds that die before
    -- the DoTs repay the AoE potency given up. The toggle stays available and
    -- is valuable on durable boss adds; it becomes a default again once a
    -- payoff model (per-target TTK or a multi-target damage model) exists.
    multiDot = false,
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
    -- Simulator sweep (300 paired seeds): Apex at 80 off-cycle beats 90 by
    -- +0.25% (p = 0.0003) and 100 is worst; the pre-burst hold measured 0.
    apexOffcycleGauge = 80,
    apexHoldForBurstSeconds = 35,
    -- Empyreal Arrow pre-burst hold; 0 = never hold (simulator: +0.7% DPS vs 5 s).
    empyrealHoldForBurstSeconds = 0,
    chargeCapLeadSeconds = 4.0, -- while pooling, spend the second charge when the third completes within this
    chargePoolSeconds = 25, -- pool shared charges when the next burst is this close (the Army's Paeon tail)
    chargeRechargeSeconds = 15, -- Heartbreak recharge; a full stack is spent while pooling only if it returns before burst

    secondWindHP = 45,
    minneHP = 60,
    troubadourHP = 70,

    -- MMOMinion exposes Player.gauge as an undocumented numeric array. These
    -- defaults match the conventional BRD layout but remain editable in-game.
    soulVoiceGaugeIndex = 4,
    repertoireGaugeIndex = 2,
    songTimerGaugeIndex = 3,

    debug = false, -- console timing trace once per second; the trace code stays, only the default changed (review 0.5.1, medium)
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
