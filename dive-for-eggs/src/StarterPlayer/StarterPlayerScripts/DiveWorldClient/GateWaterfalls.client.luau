-- Animates the falling streaks in each gate's water curtain. Runs locally on every
-- client, so the motion costs no network traffic.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage:WaitForChild("DiveWorld"):WaitForChild("Config"))

local ANIMATE_DISTANCE = 350

local world = workspace:WaitForChild(Config.WORLD_FOLDER_NAME)
local gates = world:WaitForChild("Hub"):WaitForChild("Gates")

type Streak = { part: BasePart, base: CFrame, top: number, range: number, speed: number, phase: number }
local streaks: { Streak } = {}

local function track(part: Instance)
	if not part:IsA("BasePart") or part.Name ~= "Streak" then
		return
	end
	local top = part:GetAttribute("TopY")
	local bottom = part:GetAttribute("BottomY")
	if type(top) ~= "number" or type(bottom) ~= "number" then
		return
	end
	local length = part.Size.Y
	table.insert(streaks, {
		part = part,
		base = part.CFrame - Vector3.new(0, part.Position.Y, 0),
		top = top - length / 2,
		range = math.max(0.5, top - bottom - length),
		speed = part:GetAttribute("Speed") or 14,
		phase = part:GetAttribute("Phase") or 0,
	})
end

for _, descendant in gates:GetDescendants() do
	track(descendant)
end
gates.DescendantAdded:Connect(track)

RunService.RenderStepped:Connect(function()
	local camera = workspace.CurrentCamera
	if not camera then
		return
	end
	local eye = camera.CFrame.Position
	local now = os.clock()
	for _, streak in streaks do
		local part = streak.part
		if (part.Position - eye).Magnitude < ANIMATE_DISTANCE then
			local fall = (now * streak.speed + streak.phase) % streak.range
			part.CFrame = streak.base + Vector3.new(0, streak.top - fall, 0)
		end
	end
end)
