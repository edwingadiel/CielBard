CielDancerData = CielDancerData or {}

CielDancerData.Version = "0.2.0"
CielDancerData.DancerJobID = 38
CielDancerData.ACRProfileName = "CielDancer"

-- Shared by every Ciel module: one hold switch for whichever job is being
-- played. Runtime only, never saved, so a forgotten hold cannot outlive a reload.
CielShared = CielShared or { hold = false, holdAt = 0 }

-- FFXIV action IDs. ActionList resolves availability, level sync, transformed
-- actions, cooldowns, and proc requirements at runtime.
CielDancerData.Actions = {
    Cascade = 15989,
    Fountain = 15990,
    ReverseCascade = 15991,
    Fountainfall = 15992,
    Windmill = 15993,
    Bladeshower = 15994,
    RisingWindmill = 15995,
    Bloodshower = 15996,
    StandardStep = 15997,
    TechnicalStep = 15998,
    Emboite = 15999,
    Entrechat = 16000,
    Jete = 16001,
    Pirouette = 16002,
    StandardFinish = 16003,
    TechnicalFinish = 16004,
    SaberDance = 16005,
    ClosedPosition = 16006,
    Ending = 18073,
    FanDance = 16007,
    FanDanceII = 16008,
    FanDanceIII = 16009,
    EnAvant = 16010,
    Devilment = 16011,
    ShieldSamba = 16012,
    Flourish = 16013,
    Improvisation = 16014,
    CuringWaltz = 16015,

    SingleStandardFinish = 16191,
    DoubleStandardFinish = 16192,
    SingleTechnicalFinish = 16193,
    DoubleTechnicalFinish = 16194,
    TripleTechnicalFinish = 16195,
    QuadrupleTechnicalFinish = 16196,

    Tillana = 25790,
    FanDanceIV = 25791,
    StarfallDance = 25792,

    LastDance = 36983,
    FinishingMove = 36984,
    DanceOfTheDawn = 36985,

    SecondWind = 7541,
}

CielDancerData.Statuses = {
    StandardStep = 1818,
    TechnicalStep = 1819,
    ThreefoldFanDance = 1820,
    StandardFinish = 1821,
    TechnicalFinish = 1822,
    ClosedPosition = 1823,
    DancePartner = 1824,
    Devilment = 1825,
    SilkenSymmetry = 2693,
    SilkenFlow = 2694,
    FlourishingFinish = 2698,
    FourfoldFanDance = 2699,
    FlourishingStarfall = 2700,
    FlourishingSymmetry = 3017,
    FlourishingFlow = 3018,
    LastDanceReady = 3867,
    FinishingMoveReady = 3868,
    DanceOfTheDawnReady = 3869,
}

-- Dexterity potions in preference order (newest grade first). MMOMinion
-- addresses HQ items as id + 1000000; the engine tries HQ before NQ.
CielDancerData.Potions = {
    { id = 49235, name = "Grade 4 Gemdraught of Dexterity" },
    { id = 45996, name = "Grade 3 Gemdraught of Dexterity" },
    { id = 44163, name = "Grade 2 Gemdraught of Dexterity" },
    { id = 44158, name = "Grade 1 Gemdraught of Dexterity" },
}
CielDancerData.HQOffset = 1000000

-- Every weaponskill, steps and finishes included. Used for weave counting and
-- the pending-request tier hold.
CielDancerData.GCD = {
    [15989] = true, [15990] = true, [15991] = true, [15992] = true,
    [15993] = true, [15994] = true, [15995] = true, [15996] = true,
    [15997] = true, [15998] = true,
    [15999] = true, [16000] = true, [16001] = true, [16002] = true,
    [16003] = true, [16004] = true, [16005] = true,
    [16191] = true, [16192] = true, [16193] = true, [16194] = true, [16195] = true, [16196] = true,
    [25790] = true, [25792] = true,
    [36983] = true, [36984] = true, [36985] = true,
}

CielDancerData.StandardFinishIDs = { [16003] = true, [16191] = true, [16192] = true }
CielDancerData.TechnicalFinishIDs = { [16004] = true, [16193] = true, [16194] = true, [16195] = true, [16196] = true }

-- Actions that must be requested on the player. Steps, finishes and the other
-- circles around the dancer are self-targeted; live clients report
-- IsReady=false for these when asked about an enemy target.
CielDancerData.SelfTarget = {
    [15997] = true, [15998] = true,
    [15999] = true, [16000] = true, [16001] = true, [16002] = true,
    [16003] = true, [16004] = true,
    [16191] = true, [16192] = true, [16193] = true, [16194] = true, [16195] = true, [16196] = true,
    [25790] = true, [36984] = true,
    [15993] = true, [15994] = true, [15995] = true, [15996] = true, [16008] = true,
    [16011] = true, [16013] = true, [16012] = true, [16015] = true, [16014] = true,
    [7541] = true,
    [18073] = true, -- Ending
}

-- Finishes, Tillana and Finishing Move hit a 15 yalm circle around the dancer;
-- the AoE weaponskills and Fan Dance II a 5 yalm one.
CielDancerData.FinishRadius = 15
CielDancerData.CircleRadius = 5
CielDancerData.ComboWindowSeconds = 30

-- Dance partner priority, The Balance (level 100):
--   SAM > PCT / RPR / VPR / MNK / NIN > DRG / BLM > RDM > SMN > MCH > BRD > DNC
-- Lower rank is better. Jobs inside one tier are equal; the listed order breaks
-- the tie. Tanks and healers come after every damage dealer.
CielDancerData.PartnerTiers = {
    { 34 },                 -- Samurai
    { 42, 39, 41, 20, 30 }, -- Pictomancer, Reaper, Viper, Monk, Ninja
    { 22, 25 },             -- Dragoon, Black Mage
    { 35 },                 -- Red Mage
    { 27 },                 -- Summoner
    { 31 },                 -- Machinist
    { 23 },                 -- Bard
    { 38 },                 -- Dancer
    { 32, 37, 21, 19 },     -- Dark Knight, Gunbreaker, Warrior, Paladin
    { 40, 33, 28, 24 },     -- Sage, Astrologian, Scholar, White Mage
}
CielDancerData.PartnerRank = {}
for tier, jobs in ipairs(CielDancerData.PartnerTiers) do
    for order, job in ipairs(jobs) do CielDancerData.PartnerRank[job] = tier * 100 + order end
end
CielDancerData.PartnerRange = 30

-- Every optional action is routed through this central capability table.
-- Utility automation is opt-in.
CielDancerData.AbilityDefaults = {
    StandardStep = true,
    TechnicalStep = true,
    FinishingMove = true,
    LastDance = true,
    Tillana = true,
    StarfallDance = true,
    SaberDance = true,
    DanceOfTheDawn = true,

    Fountain = true,
    ReverseCascade = true,
    Fountainfall = true,

    Devilment = true,
    Flourish = true,
    FanDance = true,
    FanDanceIII = true,
    FanDanceIV = true,

    Windmill = true,
    Bladeshower = true,
    RisingWindmill = true,
    Bloodshower = true,
    FanDanceII = true,

    SecondWind = false,
    CuringWaltz = false,
    ShieldSamba = false,
}

-- Nearby-target thresholds for the AoE replacements, counted inside the
-- five-yalm circle around the dancer. Every one is a gain at two targets
-- (Windmill 120 x 2 vs Cascade 220, Bladeshower 160 x 2 vs Fountain 280,
-- Rising Windmill 160 x 2 vs Reverse Cascade 280, Bloodshower 200 x 2 vs
-- Fountainfall 340, Fan Dance II 100 x 2 vs Fan Dance 180).
CielDancerData.AoEDefaults = {
    Windmill = 2,
    Bladeshower = 2,
    RisingWindmill = 2,
    Bloodshower = 2,
    FanDanceII = 2,
}

CielDancerData.Defaults = {
    enabled = false,
    showWindow = true,
    useAOE = true,
    aoeTargets = CielDancerData.AoEDefaults,
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
    -- GCD is treated as ready this many seconds early so requests queue
    -- without a gap; oGCDs are only weaved when at least this much GCD remains.
    gcdLeadSeconds = 0.05,
    weaveMinGcdRemaining = 0.65,
    executionMode = "FULL", -- FULL, GCD_ONLY, or OGCD_ONLY
    requireLOS = false, -- opt-in: live clients report los=false on dummies in plain view

    -- Normal users can ignore this switch and receive the optimized defaults.
    advancedEnabled = false,
    preset = "Optimized",
    abilities = CielDancerData.AbilityDefaults,

    autoTTK = true,
    manualTTK = 999,
    ttkSampleWindow = 8,
    minimumTTKConfidence = 0.50,
    terminalTTK = 20,
    idealKillMax = 30,
    terminalDumping = true,
    resourcePooling = true,

    -- Smart hold (the HOLD BURST toggle). While it is on the two-minute burst
    -- is not started and the potion is kept; everything that would otherwise
    -- be lost keeps running, and resources are pooled for the release and only
    -- spent to stay under their caps. A burst that is already running finishes.
    holdAutoReleaseSeconds = 0, -- 0 = hold until released
    holdClearsOnCombatEnd = true,
    showHoldButton = true,
    holdFlourishSeconds = 15, -- while holding, Flourish waits when Technical Step is this close

    -- A Technical dance is seven seconds of steps and a Standard one five;
    -- neither is started on a target that will not live to repay it.
    technicalMinimumTTK = 12,
    standardMinimumTTK = 10,
    -- Standard Step is held when Technical Step is this close: the dance would
    -- still be running when Technical comes up.
    standardBeforeTechnicalSeconds = 5,
    -- A Last Dance is kept for the burst only if it will still be up this long
    -- after Technical Step comes off cooldown (the dance plus the two
    -- weaponskills that open the burst).
    lastDanceBurstLeadSeconds = 15,

    -- Esprit: spent at once from 85 (overcap guard, ahead of the dances),
    -- from 80 otherwise, and pooled below that for the burst.
    saberOvercapEsprit = 85,
    saberOffcycleEsprit = 80,
    burstSaberOvercapEsprit = 80, -- inside the burst a spender goes first from this much Esprit
    -- Tillana gives 50 Esprit; it waits for the gauge to drop to this.
    tillanaMaxEsprit = 30,
    tillanaBurstDeadlineSeconds = 6, -- ...but no later than this long before the burst buffs end
    -- Thirty-second procs are pressed first once this close to lapsing, and
    -- Starfall Dance once Flourishing Starfall is.
    procUrgentSeconds = 5,
    starfallUrgentSeconds = 5,

    -- Feathers are kept for the burst and only spent at the cap outside it.
    featherOffcycleCount = 4,
    -- Flourish and Fan Dance IV are kept for a burst that is this close.
    flourishHoldSeconds = 8,
    fanDanceIVHoldSeconds = 25,

    -- Potion use is opt-in because it consumes inventory.
    usePotion = false,
    potionOnlyWithBurst = true,
    potionHQOnly = false,
    potionMinimumTTK = 8,
    potionPrepull = true,

    -- Pre-pull Standard Step: automatic when the engine pulls (requireCombat
    -- off), otherwise armed from the window.
    prepull = true,
    warnNoPartner = true,
    -- Closed Position on the best party member by The Balance's priority
    -- whenever the dancer has no partner. Out of combat a partner is also
    -- swapped for a better one that has since come into range.
    autoPartner = true,
    partnerUpgradeOutOfCombat = true,

    secondWindHP = 45,
    curingWaltzHP = 60,
    shieldSambaHP = 70,

    -- MMOMinion exposes Player.gauge as an undocumented numeric array. This is
    -- the layout FFXIVMinion's bundled Dancer profile reads; every index is
    -- editable in-game.
    featherGaugeIndex = 1,
    espritGaugeIndex = 2,
    stepGaugeIndex = 3, -- first of the four step slots
    stepsDoneGaugeIndex = 7,

    debug = false,
}

-- Presets are deliberately small overrides applied on top of the optimized
-- defaults. "Custom" is selected automatically after a manual change.
CielDancerData.Presets = {
    Optimized = {},
    Conservative = {
        maxWeaves = 1,
        terminalDumping = false,
        resourcePooling = false,
    },
    NoPartyBuffs = {
        abilities = { TechnicalStep = false, Devilment = false },
    },
    SingleTarget = {
        useAOE = false,
        abilities = { Windmill = false, Bladeshower = false, RisingWindmill = false, Bloodshower = false, FanDanceII = false },
    },
    GCDOnly = {
        executionMode = "GCD_ONLY",
    },
}
