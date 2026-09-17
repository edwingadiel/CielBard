-- Drop-in ACR profile stub. Copy this file to LuaMods/ACR/CombatRoutines/CielBard.lua
-- The CielBard module (LuaMods/CielBard) defines CielBardACRProfile; if the
-- module is not loaded yet, a placeholder keeps ACR happy.
if type(CielBardACRProfile) == "function" then
    return CielBardACRProfile()
end
return {
    name = "CielBard",
    classes = {},
    Cast = function(self) return false end,
}
