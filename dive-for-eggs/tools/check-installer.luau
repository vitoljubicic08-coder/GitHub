-- Runs the generated Studio files against the mock API, as the command bar would: the
-- installer must install every script and build the world, the plaza update must refuse
-- without a selection and install a selected statue.
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
		{
			"BubbleBuilder",
			"CentralPlazaUpdate",
			"DecorBuilder",
			"HubBuilder",
			"LightingBuilder",
			"SeabedBuilder",
			"SeabedShape",
			"StallBuilder",
			"StatueFitter",
			"Util",
			"WaterBuilder",
			"WorldBuilder",
		},
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
assert(world.Hub:FindFirstChild("CentralStalls") and #world.Hub.CentralStalls:GetChildren() == 4, "stalls missing")
print(string.format("Installer OK: scripts installed, world built with %d parts.", #Scene.parts(world)))

-- Plaza update file: with nothing selected it must refuse and change nothing.
local updateSource = fs.readFile(ROOT .. "/studio/CentralPlazaUpdate.luau")
roblox.selection = {}
assert(Loader.runChunk(updateSource, "CentralPlazaUpdate") == false, "update should refuse without a selection")
assert(not world.Hub:FindFirstChild("CentralPlaza"), "refused update changed the hub")

-- With a (fake) imported statue selected it installs it.
local Instance, Vector3, CFrame = roblox.Instance, roblox.Vector3, roblox.CFrame
local import = Instance.new("Model")
import.Name = "imported_statue"
local mesh = Instance.new("MeshPart")
mesh.MeshId = "rbxassetid://1"
mesh.Size = Vector3.new(10, 40, 10)
mesh.CFrame = CFrame.new(50, 20, 50)
mesh.Parent = import
import.Parent = roblox.workspace
roblox.selection = { import }
assert(Loader.runChunk(updateSource, "CentralPlazaUpdate") == true, "update failed")
assert(world.Hub.CentralPlaza.FishStatue == import, "statue not installed")
print("Plaza update file OK: refuses without a selection, installs the selected statue.")
