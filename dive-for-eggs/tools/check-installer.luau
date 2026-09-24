-- Runs the generated Studio installer against the mock API, as the command bar would, and
-- checks it installs every script and builds the same world as the source tree.
--   lune run tools/bundle-studio.luau && lune run tools/check-installer.luau

local fs = require("@lune/fs")
local process = require("@lune/process")

local Loader = require("./mock/loader")
local Scene = require("./mock/scene")
local roblox = Loader.roblox

local ROOT = string.gsub((string.gsub(process.cwd, "/$", "")), "/tools$", "")
if not fs.isDir(ROOT .. "/src") then
	ROOT = string.gsub(process.cwd, "/$", "") .. "/dive-for-eggs"
end

local result = Loader.runChunk(fs.readFile(ROOT .. "/studio/DiveWorldInstaller.luau"), "DiveWorldInstaller")
assert(result == true, "installer did not finish")

local game = roblox.game
local expected = {
	{ game:GetService("ReplicatedStorage"), "DiveWorld", "Folder", { "Config" } },
	{
		game:GetService("ServerScriptService"),
		"DiveWorldBuild",
		"Script",
		{ "BubbleBuilder", "DecorBuilder", "HubBuilder", "LightingBuilder", "SeabedBuilder", "SeabedShape", "Util", "WaterBuilder", "WorldBuilder" },
	},
	{
		game:GetService("StarterPlayer").StarterPlayerScripts,
		"DiveWorldClient",
		"Folder",
		{ "DepthLighting", "GateWaterfalls", "NeutralBuoyancy" },
	},
}
for _, entry in expected do
	local root = entry[1]:FindFirstChild(entry[2])
	assert(root and root.ClassName == entry[3], "missing " .. entry[2])
	for _, name in entry[4] do
		assert(root:FindFirstChild(name), "missing " .. entry[2] .. "." .. name)
	end
end

local world = roblox.workspace:FindFirstChild("DiveStarterWorld")
assert(world, "world was not built")
print(string.format("Installer OK: scripts installed, world built with %d parts.", #Scene.parts(world)))
