-- Exercises CentralPlazaUpdate against the mock API: a fake old statue, old stall, loose
-- centrepiece coral, a fake imported statue with six lanterns, and a duplicate import.
--   lune run tools/check-plaza-update.luau
-- Real Studio-only paths (EditableMesh/EditableImage) cannot run offline; the part-based
-- fallbacks are what is tested here.

local fs = require("@lune/fs")
local process = require("@lune/process")

local Loader = require("./mock/loader")
local Scene = require("./mock/scene")
local roblox = Loader.roblox
local Instance, Vector3, CFrame, Color3 = roblox.Instance, roblox.Vector3, roblox.CFrame, roblox.Color3

local ROOT = string.gsub((string.gsub(process.cwd, "/$", "")), "/tools$", "")
if not fs.isDir(ROOT .. "/src") then
	ROOT = string.gsub(process.cwd, "/$", "") .. "/dive-for-eggs"
end

local world, Config = Loader.buildWorld(ROOT .. "/src")
local game, workspace = roblox.game, roblox.workspace
local sss = game:GetService("ServerScriptService")
local Update = Loader.require(sss.DiveWorldBuild.CentralPlazaUpdate)
local StallBuilder = Loader.require(sss.DiveWorldBuild.StallBuilder)
local WorldBuilder = Loader.require(sss.DiveWorldBuild.WorldBuilder)

local failures = 0
local function check(ok: boolean, label: string, detail: string?)
	print(string.format("%s  %s%s", if ok then "PASS" else "FAIL", label, if detail then "  (" .. detail .. ")" else ""))
	if not ok then
		failures += 1
	end
end

local function part(className: string, name: string, size, cframe, parent, colour)
	local p = Instance.new(className)
	p.Name = name
	p.Size = size
	p.CFrame = cframe
	p.Anchored = false
	p.Color = colour or Color3.fromRGB(120, 120, 120)
	p.Parent = parent
	return p
end

-- Old statue in the plaza, plus a loose coral piece that belongs to it.
local old = Instance.new("Model")
old.Name = "FishStatue"
part("Part", "Pedestal", Vector3.new(10, 3, 10), CFrame.new(0, 1.5, 0), old)
part("MeshPart", "OldFish", Vector3.new(4, 12, 4), CFrame.new(0, 9, 0), old)
local oldCollision = part("Part", "Collision", Vector3.new(11, 6, 11), CFrame.new(0, 3, 0), old)
oldCollision.Transparency = 1
old.Parent = workspace
local looseCoral = part("Part", "Coral", Vector3.new(2, 3, 2), CFrame.new(12, 1.5, 6), workspace)

-- Old sonar stall near the plaza.
local oldStall = Instance.new("Model")
oldStall.Name = "SonarStall"
part("Part", "Post", Vector3.new(1, 8, 1), CFrame.new(16, 4, 16), oldStall)
part("Part", "Sign", Vector3.new(10, 2, 0.4), CFrame.new(16, 7, 12), oldStall)
oldStall.Parent = workspace

-- Something that must never be touched even though it sits in the plaza.
local spawn = Instance.new("SpawnLocation")
spawn.Name = "PlazaSpawn"
spawn.Size = Vector3.new(4, 1, 4)
spawn.CFrame = CFrame.new(5, 0.5, 5)
spawn.Parent = workspace

-- The fresh import, far from the plaza: base, big fish, six lanterns (frame + glow).
local import = Instance.new("Model")
import.Name = "meshy_fish_statue"
local importOrigin = Vector3.new(60, 5, -40)
local base = part("MeshPart", "Base", Vector3.new(16, 4, 16), CFrame.new(importOrigin + Vector3.new(0, 2, 0)), import)
base.MeshId = "rbxassetid://111"
base.TextureID = "rbxassetid://112"
local fish = part("MeshPart", "Fish", Vector3.new(8, 30, 6), CFrame.new(importOrigin + Vector3.new(0, 19, 0)), import)
fish.MeshId = "rbxassetid://113"
fish.TextureID = "rbxassetid://112"
for i = 1, 6 do
	local a = math.rad(i * 60)
	local at = importOrigin + Vector3.new(math.sin(a) * 7, 5, math.cos(a) * 7)
	local frame = part("MeshPart", "LanternFrame", Vector3.new(0.9, 1.8, 0.9), CFrame.new(at), import)
	frame.MeshId = "rbxassetid://114"
	frame.TextureID = "rbxassetid://112"
	part("Part", "LanternGlow", Vector3.new(0.5, 0.9, 0.5), CFrame.new(at), import, Color3.fromRGB(255, 200, 90))
end
import.Parent = workspace
local duplicate = import:Clone()
duplicate:PivotTo(CFrame.new(-80, 5, 80))
duplicate.Parent = workspace

-- Refuses the whole hub when it is selected by mistake.
roblox.selection = { world.Hub }
check(Update.run() == false and world.Hub.Parent == world, "refuses to treat the whole hub as the statue")

-- Real run: the user clicked the big fish mesh.
roblox.selection = { fish }
check(Update.run() == true, "update runs with the imported statue selected")

local backupRoot = game:GetService("ServerStorage"):FindFirstChild("DiveBackup")
local backedUp = {}
if backupRoot then
	for _, runFolder in backupRoot:GetChildren() do
		for _, item in runFolder:GetChildren() do
			backedUp[item] = true
		end
	end
end
check(backedUp[old] and backedUp[looseCoral], "old statue and its loose coral moved to ServerStorage.DiveBackup")
check(backedUp[oldStall], "old sonar stall moved to the backup")
check(backedUp[duplicate], "duplicate import moved to the backup")
check(spawn.Parent == workspace and not backedUp[spawn], "spawn location in the plaza left alone")

local statue = world.Hub:FindFirstChild("CentralPlaza") and world.Hub.CentralPlaza:FindFirstChild("FishStatue")
check(statue == import, "import organised as DiveStarterWorld.Hub.CentralPlaza.FishStatue")

local art, allAnchored, noArtCollision = {}, true, true
for _, p in Scene.parts(statue) do
	if p.Name ~= "StatueCollision" and p.Name ~= "LanternLight" then
		table.insert(art, p)
		allAnchored = allAnchored and p.Anchored
		noArtCollision = noArtCollision and not p.CanCollide
	end
end
check(allAnchored and noArtCollision, "all statue art anchored, detailed collision off")

local minY, maxY, reach = math.huge, -math.huge, 0
for _, p in art do
	local c, h = Scene.aabb(p)
	minY, maxY = math.min(minY, c.Y - h.Y), math.max(maxY, c.Y + h.Y)
	reach = math.max(reach, Scene.farthestCorner(p, 0, 0))
end
local baseCentre = statue.Base.Position
check(
	math.abs(minY - Config.Hub.FLOOR_Y) < 1e-6 and math.abs(baseCentre.X) < 1e-6 and math.abs(baseCentre.Z) < 1e-6,
	"statue base centred on the plaza and resting on the floor",
	string.format("base at (%.3f, %.3f), bottom %.3f", baseCentre.X, baseCentre.Z, minY)
)
local maxRadius = StallBuilder.statueRadius(Config)
check(
	math.abs(maxY - minY - Config.Statue.TARGET_HEIGHT) < 0.01 or reach <= maxRadius + 1e-6,
	"statue scaled uniformly to the target height within the statue zone",
	string.format("height %.2f, reach %.2f of %.2f", maxY - minY, reach, maxRadius)
)
check(reach <= maxRadius + 1e-6, "statue never reaches into the walking ring or the stalls")
local ratio = statue.Fish.Size.Y / statue.Base.Size.Y
check(math.abs(ratio - 30 / 4) < 1e-6, "proportions preserved (uniform scale)")

local collision = statue:FindFirstChild("StatueCollision")
check(
	collision ~= nil and collision.CanCollide and collision.Transparency == 1 and collision.Shape.Name == "Cylinder",
	"one invisible collision cylinder around the base"
)

local lights, neon, framesUntouched = 0, 0, true
for _, d in statue:GetDescendants() do
	if d.ClassName == "PointLight" then
		lights += 1
		assert(d.Brightness >= 0.7 and d.Brightness <= 1.3 and d.Range >= 7 and d.Range <= 11 and not d.Shadows)
	elseif d.Name == "LanternGlow" and d.Material.Name == "Neon" then
		neon += 1
	elseif d.Name == "LanternFrame" and d.Material.Name == "Neon" then
		framesUntouched = false
	end
end
check(lights == 6 and neon == 6 and framesUntouched, "6 lanterns: glow panels neon, frames untouched, one soft PointLight each")

local stalls = world.Hub:FindFirstChild("CentralStalls")
check(stalls ~= nil and #stalls:GetChildren() == 4, "four stalls rebuilt around the statue")

-- Re-running with nothing selected refits the same statue without duplicating anything.
roblox.selection = {}
local backupsBefore = #backupRoot:GetChildren()
check(Update.run() == true, "re-run with nothing selected reuses Hub.CentralPlaza.FishStatue")
local lightsAfter = 0
for _, d in statue:GetDescendants() do
	if d.ClassName == "PointLight" then
		lightsAfter += 1
	end
end
check(lightsAfter == 6 and #backupRoot:GetChildren() == backupsBefore, "re-run keeps 6 lights and moves nothing")

-- A full world rebuild keeps the imported statue.
local rebuilt = WorldBuilder.build()
check(rebuilt.Hub.CentralPlaza.FishStatue == statue, "rebuilding the world keeps CentralPlaza and the statue")

check(#roblox.waypoints >= 2, "undo waypoints recorded", #roblox.waypoints .. " waypoints")

print(if failures == 0 then "All plaza update checks passed." else failures .. " check(s) failed.")
process.exit(if failures == 0 then 0 else 1)
