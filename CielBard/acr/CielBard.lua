-- Drop-in ACR profile stub. Copy this file to LuaMods/ACR/CombatRoutines/CielBard.lua
-- The CielBard module (LuaMods/CielBard) defines CielBardACRProfile.
--
-- Load order is not guaranteed: ACR can evaluate its CombatRoutines folder
-- before LuaMods/CielBard has finished loading. Until v0.5.2 that left an
-- inert placeholder registered forever (0.5.1 review, High #4). The
-- placeholder below is lazy instead: every lifecycle method resolves
-- CielBardACRProfile at call time and delegates to the real profile as soon as
-- it exists, and unknown fields (GUI, region, tags, ...) are read through to
-- it as well. It also advertises the Bard job so ACR lists the routine even
-- when it is evaluated first.

if type(CielBardACRProfile) == "function" then
    return CielBardACRProfile()
end

local NAME = (type(CielBardData) == "table" and CielBardData.ACRProfileName) or "CielBard"
local BARD = (type(CielBardData) == "table" and CielBardData.BardJobID) or 23

local placeholder

local function realProfile()
    if type(CielBardACRProfile) ~= "function" then return nil end
    local ok, profile = pcall(CielBardACRProfile)
    if ok and type(profile) == "table" then return profile end
    return nil
end

-- ACR calls some hooks as profile:Method(...) and others as profile.Method(...).
-- Drop a leading self that is this placeholder (or the real profile) so the
-- delegate works under either convention.
local function delegate(method)
    return function(first, ...)
        local profile = realProfile()
        if not profile or type(profile[method]) ~= "function" then return false end
        if first == nil then return profile[method]() end
        if first == placeholder or first == profile then return profile[method](...) end
        return profile[method](first, ...)
    end
end

placeholder = setmetatable({
    name = NAME,
    classes = { [BARD] = true },
    Cast = delegate("Cast"),
    Draw = delegate("Draw"),
    DrawHeader = delegate("DrawHeader"),
    DrawFooter = delegate("DrawFooter"),
    OnOpen = delegate("OnOpen"),
    OnLoad = delegate("OnLoad"),
    OnClick = delegate("OnClick"),
    OnUpdate = delegate("OnUpdate"),
}, {
    -- Anything the placeholder does not define itself (GUI, region, tags, and
    -- any field a future ACR build reads) comes from the real profile once the
    -- module is loaded.
    __index = function(_, key)
        local profile = realProfile()
        if profile then return profile[key] end
        return nil
    end,
})

return placeholder
