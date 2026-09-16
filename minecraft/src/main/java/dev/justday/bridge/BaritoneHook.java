package dev.justday.bridge;

import baritone.api.BaritoneAPI;
import baritone.api.IBaritone;
import baritone.api.process.IBaritoneProcess;
import com.google.gson.JsonObject;

/** Loaded only when Baritone is installed (Actions checks FabricLoader first). Commands go through its API, never chat. */
final class BaritoneHook {
	private BaritoneHook() {}

	private static IBaritone b() {
		return BaritoneAPI.getProvider().getPrimaryBaritone();
	}

	/** Any Baritone command without the prefix: "mine 3 oak_log", "goto 100 64 -20", "follow player X", "explore". */
	static boolean run(String command) {
		return b().getCommandManager().execute(command);
	}

	static boolean active() {
		IBaritone b = b();
		return b.getPathingBehavior().isPathing()
				|| b.getPathingControlManager().mostRecentInControl().map(IBaritoneProcess::isActive).orElse(false);
	}

	static void stop() {
		b().getPathingBehavior().cancelEverything();
	}

	static JsonObject status() {
		IBaritone b = b();
		JsonObject o = new JsonObject();
		o.addProperty("active", active());
		o.addProperty("pathing", b.getPathingBehavior().isPathing());
		b.getPathingControlManager().mostRecentInControl()
				.ifPresent(p -> o.addProperty("process", p.displayName()));
		var goal = b.getPathingBehavior().getGoal();
		o.addProperty("goal", goal == null ? null : goal.toString());
		b.getPathingBehavior().estimatedTicksToGoal().ifPresent(t -> o.addProperty("eta_s", Math.round(t / 20)));
		return o;
	}
}
