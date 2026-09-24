-- Neutral buoyancy: outside the bubble an idle swimmer holds depth instead of drifting up.
-- While swimming with no movement or jump input, a line-only LinearVelocity settles the
-- vertical velocity to zero. Any input releases it so normal swimming is untouched.

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local player = Players.LocalPlayer
local IDLE_INPUT = 0.05

local function attach(character: Model)
	local humanoid = character:WaitForChild("Humanoid") :: Humanoid
	local root = character:WaitForChild("HumanoidRootPart") :: BasePart

	local attachment = Instance.new("Attachment")
	attachment.Name = "NeutralBuoyancyAttachment"
	attachment.Parent = root

	local hold = Instance.new("LinearVelocity")
	hold.Name = "NeutralBuoyancy"
	hold.Attachment0 = attachment
	hold.RelativeTo = Enum.ActuatorRelativeTo.World
	hold.VelocityConstraintMode = Enum.VelocityConstraintMode.Line
	hold.LineDirection = Vector3.yAxis
	hold.LineVelocity = 0
	hold.Enabled = false
	hold.Parent = root

	local connection
	connection = RunService.Heartbeat:Connect(function()
		if not character.Parent or humanoid.Health <= 0 then
			connection:Disconnect()
			return
		end
		local idle = humanoid:GetState() == Enum.HumanoidStateType.Swimming
			and humanoid.MoveDirection.Magnitude < IDLE_INPUT
			and not humanoid.Jump
		if idle then
			-- Strong enough to cancel buoyancy within a fraction of a second, gentle
			-- enough that the stop reads as settling rather than snapping.
			hold.MaxForce = root.AssemblyMass * workspace.Gravity * 3
		end
		hold.Enabled = idle
	end)
end

if player.Character then
	task.spawn(attach, player.Character)
end
player.CharacterAdded:Connect(attach)
