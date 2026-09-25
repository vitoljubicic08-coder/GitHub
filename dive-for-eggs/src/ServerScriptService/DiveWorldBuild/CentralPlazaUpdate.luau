-- Studio edit-mode tool: installs the imported fish statue (selected in Explorer) as the
-- central statue, rebuilds the four stalls around it, and clears out the old statue, old
-- stalls and duplicate imports. Nothing is deleted: replaced objects are moved to
-- ServerStorage.DiveBackup, and the whole run is one undo step (Ctrl+Z).
--   require(game.ServerScriptService.DiveWorldBuild.CentralPlazaUpdate).run()

local ChangeHistoryService = game:GetService("ChangeHistoryService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Selection = game:GetService("Selection")
local ServerStorage = game:GetService("ServerStorage")

local Config = require(ReplicatedStorage:WaitForChild("DiveWorld"):WaitForChild("Config"))
local StallBuilder = require(script.Parent.StallBuilder)
local StatueFitter = require(script.Parent.StatueFitter)
local Util = require(script.Parent.Util)

local CentralPlazaUpdate = {}

local NEVER_MOVE = { "aquarium", "gate", "bubble", "spawn", "terrain", "camera" }
local MAX_STATUE_PARTS = 300

local function log(message: string, ...)
	print("[CentralPlaza] " .. string.format(message, ...))
end

local function lowerHas(name: string, words: { string }): boolean
	local lower = string.lower(name)
	for _, word in words do
		if string.find(lower, word, 1, true) then
			return true
		end
	end
	return false
end

-- World-space bounds of everything physical under an instance (nil if nothing).
local function bounds(instance: Instance): (Vector3?, Vector3?)
	local list = if instance:IsA("BasePart") then { instance } else instance:GetDescendants()
	local lo, hi = nil, nil
	for _, part in list do
		if part:IsA("BasePart") then
			local half = part.Size / 2
			local c = part.CFrame
			for _, sx in { -1, 1 } do
				for _, sy in { -1, 1 } do
					for _, sz in { -1, 1 } do
						local p = c * Vector3.new(sx * half.X, sy * half.Y, sz * half.Z)
						lo = if lo then Vector3.new(math.min(lo.X, p.X), math.min(lo.Y, p.Y), math.min(lo.Z, p.Z)) else p
						hi = if hi then Vector3.new(math.max(hi.X, p.X), math.max(hi.Y, p.Y), math.max(hi.Z, p.Z)) else p
					end
				end
			end
		end
	end
	return lo, hi
end

-- Farthest horizontal distance of a bounds box from a point.
local function reachFrom(lo: Vector3, hi: Vector3, centre: Vector3): number
	local dx = math.max(math.abs(lo.X - centre.X), math.abs(hi.X - centre.X))
	local dz = math.max(math.abs(lo.Z - centre.Z), math.abs(hi.Z - centre.Z))
	return math.sqrt(dx * dx + dz * dz)
end

------------------------------------------------------------------------ plaza

type Plaza = { centre: Vector3, radius: number, hub: Instance, source: string }

local function findPlaza(): (Plaza?, string?)
	local world = workspace:FindFirstChild(Config.WORLD_FOLDER_NAME)
	local hub = world and world:FindFirstChild("Hub")
	if hub then
		return {
			centre = Vector3.new(0, Config.Hub.FLOOR_Y, 0),
			radius = Config.Hub.PLAZA_RADIUS,
			hub = hub,
			source = "DiveStarterWorld hub (generated, centre is exactly 0, 0)",
		}
	end
	-- Not our generated hub: use the largest flat part whose name says it is the plaza.
	local best, bestArea = nil, 0
	for _, d in workspace:GetDescendants() do
		if d:IsA("BasePart") and lowerHas(d.Name, { "plaza" }) then
			local lo, hi = bounds(d)
			if lo and hi and hi.Y - lo.Y < 10 then
				local area = (hi.X - lo.X) * (hi.Z - lo.Z)
				if area > bestArea then
					best, bestArea = { lo = lo, hi = hi, part = d }, area
				end
			end
		end
	end
	if best then
		local hubModel = workspace:FindFirstChild("Hub") or Util.model("Hub", workspace)
		return {
			centre = Vector3.new((best.lo.X + best.hi.X) / 2, best.hi.Y, (best.lo.Z + best.hi.Z) / 2),
			radius = math.min(best.hi.X - best.lo.X, best.hi.Z - best.lo.Z) / 2,
			hub = hubModel,
			source = "plaza part " .. best.part:GetFullName(),
		}
	end
	return nil,
		"Could not find the plaza. Build the Dive starter world first (DiveWorldInstaller), "
			.. "or name your plaza floor part so it contains the word 'Plaza'."
end

------------------------------------------------------------------------ statue selection

local function meshIds(instance: Instance): string
	local ids = {}
	local list = if instance:IsA("BasePart") then { instance } else instance:GetDescendants()
	for _, d in list do
		if d:IsA("MeshPart") then
			table.insert(ids, (d :: MeshPart).MeshId)
		end
	end
	table.sort(ids)
	return table.concat(ids, "|")
end

local function looksLikeImport(instance: Instance): (boolean, string?)
	local parts, meshesFound = 0, 0
	local list = if instance:IsA("BasePart") then { instance } else instance:GetDescendants()
	for _, d in list do
		if d:IsA("BaseScript") then
			return false, "it contains scripts"
		elseif d:IsA("BasePart") then
			parts += 1
			if d:IsA("MeshPart") then
				meshesFound += 1
			end
		end
	end
	if meshesFound == 0 then
		return false, "it has no MeshParts"
	elseif parts > MAX_STATUE_PARTS then
		return false, string.format("it has %d parts, far more than an imported statue", parts)
	elseif instance:FindFirstChild("CentralStalls") or instance:FindFirstChild("Floor") then
		return false, "it looks like part of the hub"
	end
	return true, nil
end

local function selectedStatue(plaza: Plaza): (Instance?, string?)
	local selected = Selection:Get()
	if #selected > 1 then
		return nil, "Select only the imported statue (one object) in Explorer, then run again."
	end
	local target = selected[1]
	if not target then
		local existing = plaza.hub:FindFirstChild("CentralPlaza")
		existing = existing and existing:FindFirstChild("FishStatue")
		if existing then
			return existing, nil
		end
		return nil, "Select the imported fish statue in Explorer first, then run again."
	end
	-- Clicking in the viewport or Explorer may pick an inner mesh; climb to the import.
	while target.Parent and target.Parent:IsA("Model") and target.Parent ~= plaza.hub do
		target = target.Parent
	end
	local ok, why = looksLikeImport(target)
	if not ok then
		return nil, string.format("'%s' doesn't look like the imported statue: %s.", target:GetFullName(), why or "")
	end
	return target, nil
end

------------------------------------------------------------------------ backup

local backupFolder: Folder? = nil
local moved: { string } = {}

local function backup(instance: Instance, reason: string)
	if not backupFolder then
		local root = ServerStorage:FindFirstChild("DiveBackup") or Util.folder("DiveBackup", ServerStorage)
		backupFolder = Util.folder(os.date("Plaza update %Y-%m-%d %H.%M.%S") :: string, root)
	end
	table.insert(moved, string.format("%s (%s)", instance:GetFullName(), reason))
	instance.Parent = backupFolder
end

local function protected(instance: Instance, keep: { Instance }): boolean
	if instance:IsA("Terrain") or instance:IsA("Camera") or instance:IsA("SpawnLocation") then
		return true
	end
	if instance:IsA("Model") and Players:GetPlayerFromCharacter(instance) then
		return true
	end
	if lowerHas(instance.Name, NEVER_MOVE) then
		return true
	end
	for _, k in keep do
		if instance == k or instance:IsDescendantOf(k) then
			return true
		end
	end
	return false
end

-- Containers that hold something we keep are searched, never moved as a whole.
local function holdsKept(instance: Instance, keep: { Instance }): boolean
	for _, k in keep do
		if k:IsDescendantOf(instance) then
			return true
		end
	end
	return false
end

local function isContainer(instance: Instance): boolean
	return instance:IsA("Model") or instance:IsA("Folder")
end

-- Old stalls anywhere near the plaza (they are replaced by the four generated stalls).
local function collectOldStalls(container: Instance, plaza: Plaza, keep: { Instance }, out: { Instance })
	for _, child in container:GetChildren() do
		if not protected(child, keep) then
			local lo, hi = bounds(child)
			local near = lo ~= nil and hi ~= nil and reachFrom(lo, hi, plaza.centre) <= plaza.radius + 30
			if near and lowerHas(child.Name, { "stall" }) and not holdsKept(child, keep) then
				table.insert(out, child)
			elseif lo and isContainer(child) then
				collectOldStalls(child, plaza, keep, out)
			end
		end
	end
end

-- Anything else standing inside the plaza: the old statue and all of its pieces
-- (fish, pedestal, coral, lights, invisible collision, helper parts).
local function collectOldCentrepiece(container: Instance, plaza: Plaza, keep: { Instance }, out: { Instance })
	for _, child in container:GetChildren() do
		if not protected(child, keep) and (child:IsA("BasePart") or isContainer(child)) then
			local lo, hi = bounds(child)
			if lo and hi then
				local inside = reachFrom(lo, hi, plaza.centre) <= plaza.radius + 2
				if inside and hi.Y > plaza.centre.Y + 2 and not holdsKept(child, keep) then
					table.insert(out, child)
				elseif isContainer(child) then
					collectOldCentrepiece(child, plaza, keep, out)
				end
			end
		end
	end
end

------------------------------------------------------------------------ run

function CentralPlazaUpdate.run(): boolean
	backupFolder, moved = nil, {}

	local plaza, plazaError = findPlaza()
	if not plaza then
		warn("[CentralPlaza] " .. (plazaError or "plaza not found") .. " Nothing was changed.")
		return false
	end
	local statue, statueError = selectedStatue(plaza)
	if not statue then
		warn("[CentralPlaza] " .. (statueError or "statue not found") .. " Nothing was changed.")
		return false
	end
	log("Plaza: %s, radius %.1f.", plaza.source, plaza.radius)
	log("New statue: %s.", statue:GetFullName())

	pcall(function()
		ChangeHistoryService:SetWaypoint("Before central plaza update")
	end)

	local statueIds = meshIds(statue)
	local stallsFolder = plaza.hub:FindFirstChild("CentralStalls")
	local keep = { statue }
	if stallsFolder then
		table.insert(keep, stallsFolder)
	end

	local oldStalls = {}
	collectOldStalls(workspace, plaza, keep, oldStalls)
	for _, item in oldStalls do
		backup(item, "old stall")
	end

	local oldCentre = {}
	collectOldCentrepiece(workspace, plaza, keep, oldCentre)
	for _, item in oldCentre do
		backup(item, "old statue / centrepiece")
	end

	-- Organise the import as Hub.CentralPlaza.FishStatue (one Model).
	local plazaFolder = plaza.hub:FindFirstChild("CentralPlaza") or Util.folder("CentralPlaza", plaza.hub)
	local model: Model
	if statue:IsA("Model") then
		model = statue :: Model
	else
		model = Instance.new("Model")
		if statue:IsA("BasePart") then
			statue.Parent = model
		else
			for _, child in statue:GetChildren() do
				child.Parent = model
			end
			statue:Destroy()
		end
	end
	model.Name = "FishStatue"
	model.Parent = plazaFolder

	-- Extra copies of the same import left elsewhere (only when every mesh has an asset id).
	local idsUsable = statueIds ~= "" and not string.find("|" .. statueIds .. "|", "||", 1, true)
	for _, d in if idsUsable then workspace:GetDescendants() else {} do
		if
			d:IsDescendantOf(workspace)
			and (d:IsA("Model") or d:IsA("MeshPart"))
			and d ~= model
			and not d:IsDescendantOf(model)
			and not model:IsDescendantOf(d)
			and meshIds(d) == statueIds
		then
			backup(d, "duplicate import")
		end
	end

	StallBuilder.build(plaza.hub, Config, plaza.centre)
	log("Built 4 stalls facing the statue (template in ServerStorage.DiveWorldTemplates).")

	local maxRadius = StallBuilder.statueRadius(Config)
	local ok, result = pcall(StatueFitter.fit, model, Config, plaza.centre, maxRadius)
	if not ok then
		warn("[CentralPlaza] Statue fitting failed: " .. tostring(result) .. ". Press Ctrl+Z to undo this run.")
		return false
	end

	local shape = result.shape
	log(
		"Statue scaled x%.3f: %.1f studs tall, base radius %.1f, widest reach %.1f (limit %.1f).",
		result.scale,
		shape.height,
		shape.baseRadius,
		shape.reach,
		maxRadius
	)
	log("Base centred at (%.2f, %.2f, %.2f), resting on the floor.", shape.base.X, shape.base.Y, shape.base.Z)
	log("Lanterns lit: %d (%s).", result.lanterns, result.lanternMethod)
	if result.lanterns == 0 then
		log(
			"To light them by hand: put a small Part named LanternMarker inside FishStatue at each lantern, then run again."
		)
	end
	for _, note in result.notes do
		log("Note: %s.", note)
	end
	if #moved == 0 then
		log("Nothing else needed moving.")
	else
		log("Moved %d object(s) to %s:", #moved, if backupFolder then backupFolder:GetFullName() else "backup")
		for _, line in moved do
			log("  - %s", line)
		end
		log("Check the plaza, then delete that backup folder when you are happy.")
	end

	pcall(function()
		ChangeHistoryService:SetWaypoint("Central plaza update")
	end)
	Selection:Set({ model })
	return true
end

return CentralPlazaUpdate
