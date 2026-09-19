-- Drop-in ACR profile stub. Copy this file to LuaMods/ACR/CombatRoutines/CielMachinist.lua
-- The CielMachinist module (LuaMods/CielMachinist) defines CielMachinistACRProfile.
--
-- Load order is not guaranteed: ACR can evaluate its CombatRoutines folder
-- before LuaMods/CielMachinist has finished loading. The placeholder below is
-- lazy rather than inert: every lifecycle method resolves
-- CielMachinistACRProfile at call time and delegates to the real profile as soon as
-- it exists, and unknown fields (GUI, region, tags, ...) are read through to
-- it as well. It also advertises the Machinist job so ACR lists the routine even
-- when it is evaluated first.

if type(CielMachinistACRProfile) == "function" then
    return CielMachinistACRProfile()
end

local NAME = (type(CielMachinistData) == "table" and CielMachinistData.ACRProfileName) or "CielMachinist"
local MACHINIST = (type(CielMachinistData) == "table" and CielMachinistData.MachinistJobID) or 31

local placeholder

local function realProfile()
    if type(CielMachinistACRProfile) ~= "function" then return nil end
    local ok, profile = pcall(CielMachinistACRProfile)
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
    classes = { [MACHINIST] = true },
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
