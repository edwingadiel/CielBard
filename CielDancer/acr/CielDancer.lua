-- Drop-in ACR profile stub. Copy this file to LuaMods/ACR/CombatRoutines/CielDancer.lua
-- The CielDancer module (LuaMods/CielDancer) defines CielDancerACRProfile.
--
-- Load order is not guaranteed: ACR can evaluate its CombatRoutines folder
-- before LuaMods/CielDancer has finished loading. The placeholder below is
-- lazy rather than inert: every lifecycle method resolves
-- CielDancerACRProfile at call time and delegates to the real profile as soon as
-- it exists, and unknown fields (GUI, region, tags, ...) are read through to
-- it as well. It also advertises the Dancer job so ACR lists the routine even
-- when it is evaluated first.

if type(CielDancerACRProfile) == "function" then
    return CielDancerACRProfile()
end

local NAME = (type(CielDancerData) == "table" and CielDancerData.ACRProfileName) or "CielDancer"
local DANCER = (type(CielDancerData) == "table" and CielDancerData.DancerJobID) or 38

local placeholder

local function realProfile()
    if type(CielDancerACRProfile) ~= "function" then return nil end
    local ok, profile = pcall(CielDancerACRProfile)
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
    classes = { [DANCER] = true },
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
