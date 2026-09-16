package dev.justday.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.CraftingMenu;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.CompletableFuture;
import java.util.function.Predicate;
import java.util.regex.Pattern;

/** Everything runs on the game thread. Instant commands answer at once; long ones become a ticked Task. */
final class Actions {
	private Actions() {}

	static final double REACH = 4.5;

	interface Task {
		/** One game tick. Return a result to finish, null to keep going. */
		JsonObject tick(Minecraft mc);

		default void cancel(Minecraft mc) {}
	}

	private static Task current;
	private static CompletableFuture<JsonObject> currentDone;

	static boolean baritone() {
		return FabricLoader.getInstance().isModLoaded("baritone");
	}

	static void start(String cmd, JsonObject req, CompletableFuture<JsonObject> done) {
		Minecraft mc = Minecraft.getInstance();
		switch (cmd) {
			case "state" -> done.complete(state(mc));
			case "find" -> done.complete(find(mc, str(req, "block", "*_log"), num(req, "radius", 32), num(req, "height", 16), num(req, "limit", 10)));
			case "look" -> {
				if (req.has("x")) lookAt(mc.player, new Vec3(dbl(req, "x"), dbl(req, "y"), dbl(req, "z")));
				else {
					mc.player.setYRot((float) dbl(req, "yaw"));
					mc.player.setXRot((float) Mth.clamp(dbl(req, "pitch"), -90, 90));
				}
				done.complete(ok());
			}
			case "select" -> done.complete(select(mc, str(req, "item", "")));
			case "close" -> {
				mc.player.closeContainer();
				done.complete(ok());
			}
			case "stop" -> {
				abort();
				if (baritone()) BaritoneHook.stop();
				done.complete(ok());
			}
			case "baritone" -> {
				if (!baritone()) done.complete(Bridge.error("Baritone is not installed"));
				else {
					JsonObject o = ok();
					o.addProperty("accepted", BaritoneHook.run(str(req, "command", "")));
					done.complete(o);
				}
			}
			case "wait" -> run(new WaitTask(num(req, "timeout", 60)), done);
			case "mine" -> run(new MineTask(pos(req), num(req, "timeout", 20)), done);
			case "place" -> done.complete(place(mc, str(req, "item", ""), req.has("x") ? pos(req) : null));
			case "use" -> done.complete(useBlock(mc, pos(req)));
			case "craft" -> run(new CraftTask(str(req, "item", ""), num(req, "count", 1)), done);
			default -> done.complete(Bridge.error("unknown command " + cmd));
		}
	}

	private static void run(Task t, CompletableFuture<JsonObject> done) {
		abort();
		current = t;
		currentDone = done;
	}

	static void abort() {
		if (current != null) {
			current.cancel(Minecraft.getInstance());
			currentDone.complete(Bridge.error("stopped"));
		}
		current = null;
		currentDone = null;
	}

	static void tick(Minecraft mc) {
		if (current == null) return;
		JsonObject result;
		try {
			result = mc.player == null ? Bridge.error("left the world") : current.tick(mc);
		} catch (Exception e) {
			Bridge.LOG.error("task failed", e);
			result = Bridge.error(e.getClass().getSimpleName() + ": " + e.getMessage());
		}
		if (result != null) {
			CompletableFuture<JsonObject> done = currentDone;
			current = null;
			currentDone = null;
			if (mc.player != null && !result.has("state")) result.add("state", brief(mc));
			done.complete(result);
		}
	}

	// ───────────────────────── reading the world ─────────────────────────

	static String id(ResourceLocation key) {
		return key.getNamespace().equals("minecraft") ? key.getPath() : key.toString();
	}

	static String itemId(ItemStack s) {
		return id(BuiltInRegistries.ITEM.getKey(s.getItem()));
	}

	static String blockId(BlockState s) {
		return id(BuiltInRegistries.BLOCK.getKey(s.getBlock()));
	}

	/** "oak_log", "*_log", "#log" (any log/stem), several separated by commas. */
	static Predicate<String> matcher(String spec) {
		List<Pattern> ps = new ArrayList<>();
		for (String part : spec.split(",")) {
			String p = part.trim().toLowerCase();
			if (p.isEmpty()) continue;
			String re = switch (p) {
				case "#log", "#logs" -> "(stripped_)?\\w+_(log|wood|stem|hyphae)";
				case "#planks" -> "\\w+_planks";
				case "#stone", "#cobble" -> "cobblestone|cobbled_deepslate|blackstone";
				case "#coal" -> "coal|charcoal";
				default -> Pattern.quote(p).replace("*", "\\E.*\\Q");
			};
			ps.add(Pattern.compile(re));
		}
		return s -> ps.stream().anyMatch(p -> p.matcher(s).matches());
	}

	static JsonObject ok() {
		JsonObject o = new JsonObject();
		o.addProperty("ok", true);
		return o;
	}

	static JsonArray arr(double... v) {
		JsonArray a = new JsonArray();
		for (double d : v) a.add(Math.round(d * 100) / 100.0);
		return a;
	}

	static Map<String, Integer> inventory(LocalPlayer p) {
		Map<String, Integer> out = new TreeMap<>();
		var inv = p.getInventory();
		for (int i = 0; i < 36; i++) {
			ItemStack s = inv.getItem(i);
			if (!s.isEmpty()) out.merge(itemId(s), s.getCount(), Integer::sum);
		}
		return out;
	}

	static int count(LocalPlayer p, Predicate<String> m) {
		return inventory(p).entrySet().stream().filter(e -> m.test(e.getKey())).mapToInt(Map.Entry::getValue).sum();
	}

	static JsonObject brief(Minecraft mc) {
		LocalPlayer p = mc.player;
		JsonObject o = new JsonObject();
		o.add("pos", arr(p.getX(), p.getY(), p.getZ()));
		o.addProperty("health", p.getHealth());
		o.add("inventory", Bridge.GSON.toJsonTree(inventory(p)));
		return o;
	}

	static JsonObject state(Minecraft mc) {
		LocalPlayer p = mc.player;
		JsonObject o = ok();
		o.add("pos", arr(p.getX(), p.getY(), p.getZ()));
		BlockPos bp = p.blockPosition();
		o.add("block", arr(bp.getX(), bp.getY(), bp.getZ()));
		o.addProperty("yaw", Math.round(Mth.wrapDegrees(p.getYRot())));
		o.addProperty("pitch", Math.round(p.getXRot()));
		o.addProperty("facing", p.getDirection().getName());
		o.addProperty("health", p.getHealth());
		o.addProperty("food", p.getFoodData().getFoodLevel());
		o.addProperty("air", p.getAirSupply());
		o.addProperty("on_ground", p.onGround());
		o.addProperty("in_water", p.isInWater());
		o.addProperty("dimension", id(mc.level.dimension().location()));
		o.addProperty("singleplayer", mc.isSingleplayer());
		long t = mc.level.getDayTime() % 24000;
		o.addProperty("time", t);
		o.addProperty("night", t > 12800 && t < 23200);
		o.addProperty("screen", mc.screen == null ? null : mc.screen.getClass().getSimpleName());
		o.addProperty("container", p.containerMenu == p.inventoryMenu ? null : p.containerMenu.getClass().getSimpleName());
		var inv = p.getInventory();
		o.addProperty("selected_slot", inv.getSelectedSlot());
		o.addProperty("holding", inv.getSelectedItem().isEmpty() ? null : itemId(inv.getSelectedItem()));
		JsonArray hotbar = new JsonArray();
		for (int i = 0; i < 9; i++) {
			ItemStack s = inv.getItem(i);
			hotbar.add(s.isEmpty() ? "" : itemId(s) + " x" + s.getCount());
		}
		o.add("hotbar", hotbar);
		o.add("inventory", Bridge.GSON.toJsonTree(inventory(p)));
		HitResult hit = mc.hitResult;
		if (hit instanceof BlockHitResult bh && hit.getType() == HitResult.Type.BLOCK) {
			JsonObject tgt = new JsonObject();
			tgt.addProperty("block", blockId(mc.level.getBlockState(bh.getBlockPos())));
			tgt.add("pos", arr(bh.getBlockPos().getX(), bh.getBlockPos().getY(), bh.getBlockPos().getZ()));
			o.add("looking_at", tgt);
		} else if (hit instanceof EntityHitResult eh) {
			o.addProperty("looking_at", id(BuiltInRegistries.ENTITY_TYPE.getKey(eh.getEntity().getType())));
		}
		JsonArray mobs = new JsonArray();
		for (Entity e : mc.level.entitiesForRendering()) {
			if (e instanceof Enemy && e.distanceTo(p) < 24) {
				JsonObject m = new JsonObject();
				m.addProperty("type", id(BuiltInRegistries.ENTITY_TYPE.getKey(e.getType())));
				m.addProperty("distance", Math.round(e.distanceTo(p)));
				m.add("pos", arr(e.getX(), e.getY(), e.getZ()));
				mobs.add(m);
			}
		}
		o.add("hostiles", mobs);
		if (baritone()) o.add("baritone", BaritoneHook.status());
		o.addProperty("baritone_installed", baritone());
		return o;
	}

	static JsonObject find(Minecraft mc, String spec, int radius, int height, int limit) {
		Predicate<String> m = matcher(spec);
		LocalPlayer p = mc.player;
		BlockPos c = p.blockPosition();
		radius = Math.min(radius, 96);
		int minY = Math.max(mc.level.getMinY(), c.getY() - height), maxY = Math.min(mc.level.getMaxY(), c.getY() + height);
		record Hit(BlockPos pos, String id, double d) {}
		List<Hit> hits = new ArrayList<>();
		BlockPos.MutableBlockPos q = new BlockPos.MutableBlockPos();
		for (int x = c.getX() - radius; x <= c.getX() + radius; x++)
			for (int z = c.getZ() - radius; z <= c.getZ() + radius; z++) {
				if (!mc.level.hasChunk(x >> 4, z >> 4)) continue;
				for (int y = minY; y <= maxY; y++) {
					q.set(x, y, z);
					BlockState s = mc.level.getBlockState(q);
					if (s.isAir()) continue;
					String id = blockId(s);
					if (m.test(id)) hits.add(new Hit(q.immutable(), id, Math.sqrt(q.distToCenterSqr(p.getEyePosition()))));
				}
			}
		hits.sort(Comparator.comparingDouble(Hit::d));
		JsonObject o = ok();
		o.addProperty("total", hits.size());
		JsonArray a = new JsonArray();
		for (Hit h : hits.subList(0, Math.min(limit, hits.size()))) {
			JsonObject b = new JsonObject();
			b.addProperty("block", h.id);
			b.add("pos", arr(h.pos.getX(), h.pos.getY(), h.pos.getZ()));
			b.addProperty("distance", Math.round(h.d * 10) / 10.0);
			b.addProperty("reachable", h.d <= REACH);
			a.add(b);
		}
		o.add("blocks", a);
		return o;
	}

	// ───────────────────────── acting ─────────────────────────

	static void lookAt(LocalPlayer p, Vec3 target) {
		Vec3 d = target.subtract(p.getEyePosition());
		float yaw = (float) (Mth.atan2(d.z, d.x) * Mth.RAD_TO_DEG) - 90f;
		float pitch = (float) -(Mth.atan2(d.y, Math.sqrt(d.x * d.x + d.z * d.z)) * Mth.RAD_TO_DEG);
		p.setYRot(yaw);
		p.setYHeadRot(yaw);
		p.setXRot(Mth.clamp(pitch, -90f, 90f));
	}

	/** Put an item matching `spec` into the hand: pick its hotbar slot, or swap it in from the main inventory. */
	static JsonObject select(Minecraft mc, String spec) {
		LocalPlayer p = mc.player;
		Predicate<String> m = matcher(spec);
		var inv = p.getInventory();
		for (int i = 0; i < 9; i++)
			if (!inv.getItem(i).isEmpty() && m.test(itemId(inv.getItem(i)))) {
				inv.setSelectedSlot(i);
				return ok();
			}
		for (int i = 9; i < 36; i++)
			if (!inv.getItem(i).isEmpty() && m.test(itemId(inv.getItem(i)))) {
				if (p.containerMenu != p.inventoryMenu) p.closeContainer();
				// InventoryMenu: main inventory slots 9..35 keep their index; SWAP moves it into the selected hotbar slot
				mc.gameMode.handleInventoryMouseClick(p.inventoryMenu.containerId, i, inv.getSelectedSlot(), ClickType.SWAP, p);
				return ok();
			}
		return Bridge.error("no " + spec + " in the inventory");
	}

	static Direction faceToward(BlockPos pos, Vec3 eye) {
		Vec3 d = eye.subtract(Vec3.atCenterOf(pos));
		return Direction.getApproximateNearest(d.x, d.y, d.z);
	}

	static JsonObject useBlock(Minecraft mc, BlockPos pos) {
		LocalPlayer p = mc.player;
		if (Math.sqrt(pos.distToCenterSqr(p.getEyePosition())) > REACH) return Bridge.error("too far: walk closer first");
		Direction face = faceToward(pos, p.getEyePosition());
		Vec3 at = Vec3.atCenterOf(pos).add(face.getStepX() * 0.5, face.getStepY() * 0.5, face.getStepZ() * 0.5);
		lookAt(p, at);
		var r = mc.gameMode.useItemOn(p, InteractionHand.MAIN_HAND, new BlockHitResult(at, face, pos, false));
		p.swing(InteractionHand.MAIN_HAND);
		JsonObject o = ok();
		o.addProperty("result", r.toString());
		return o;
	}

	/** Place a block from the inventory at `pos` (or a free spot next to the player when pos is null). */
	static JsonObject place(Minecraft mc, String spec, BlockPos pos) {
		LocalPlayer p = mc.player;
		if (pos == null) pos = freeSpot(mc);
		if (pos == null) return Bridge.error("no free spot next to the player");
		if (!mc.level.getBlockState(pos).canBeReplaced()) return Bridge.error("that spot is occupied by " + blockId(mc.level.getBlockState(pos)));
		if (p.getBoundingBox().intersects(new net.minecraft.world.phys.AABB(pos))) return Bridge.error("the player stands there");
		JsonObject sel = select(mc, spec);
		if (!sel.get("ok").getAsBoolean()) return sel;
		for (Direction d : Direction.values()) {
			BlockPos support = pos.relative(d);
			BlockState s = mc.level.getBlockState(support);
			if (s.isAir() || s.canBeReplaced()) continue;
			Direction face = d.getOpposite();
			Vec3 at = Vec3.atCenterOf(support).add(face.getStepX() * 0.5, face.getStepY() * 0.5, face.getStepZ() * 0.5);
			if (at.distanceTo(p.getEyePosition()) > REACH) continue;
			lookAt(p, at);
			var r = mc.gameMode.useItemOn(p, InteractionHand.MAIN_HAND, new BlockHitResult(at, face, support, false));
			p.swing(InteractionHand.MAIN_HAND);
			JsonObject o = ok();
			o.addProperty("result", r.toString());
			o.add("pos", arr(pos.getX(), pos.getY(), pos.getZ()));
			return o;
		}
		return Bridge.error("nothing to place it against within reach");
	}

	static BlockPos freeSpot(Minecraft mc) {
		BlockPos base = mc.player.blockPosition();
		Direction ahead = mc.player.getDirection();
		List<BlockPos> order = new ArrayList<>();
		for (int dist = 1; dist <= 2; dist++) {
			order.add(base.relative(ahead, dist));
			order.add(base.relative(ahead.getClockWise(), dist));
			order.add(base.relative(ahead.getCounterClockWise(), dist));
			order.add(base.relative(ahead.getOpposite(), dist));
		}
		for (BlockPos q : order) {
			if (mc.level.getBlockState(q).canBeReplaced() && mc.level.getBlockState(q.above()).canBeReplaced()
					&& !mc.level.getBlockState(q.below()).canBeReplaced()) return q;
		}
		return null;
	}

	static BlockPos pos(JsonObject req) {
		return BlockPos.containing(dbl(req, "x"), dbl(req, "y"), dbl(req, "z"));
	}

	static String str(JsonObject o, String k, String def) {
		return o.has(k) ? o.get(k).getAsString() : def;
	}

	static int num(JsonObject o, String k, int def) {
		return o.has(k) ? o.get(k).getAsInt() : def;
	}

	static double dbl(JsonObject o, String k) {
		if (!o.has(k)) throw new IllegalArgumentException("missing " + k);
		return o.get(k).getAsDouble();
	}

	// ───────────────────────── tasks ─────────────────────────

	/** Wait until Baritone has finished (or gave up). */
	static final class WaitTask implements Task {
		private final int maxTicks;
		private int ticks;

		WaitTask(int seconds) {
			maxTicks = seconds * 20;
		}

		@Override
		public JsonObject tick(Minecraft mc) {
			ticks++;
			if (!baritone()) return Bridge.error("Baritone is not installed");
			if (mc.player.isDeadOrDying()) return Bridge.error("the player died");
			if (ticks > 10 && !BaritoneHook.active()) {
				JsonObject o = ok();
				o.addProperty("finished_after_s", ticks / 20.0);
				return o;
			}
			if (ticks >= maxTicks) {
				JsonObject o = ok();
				o.addProperty("still_running", true);
				o.add("baritone", BaritoneHook.status());
				return o;
			}
			return null;
		}
	}

	/** Break one block in reach with whatever is in the hand. */
	static final class MineTask implements Task {
		private final BlockPos pos;
		private final int maxTicks;
		private int ticks;

		MineTask(BlockPos pos, int seconds) {
			this.pos = pos;
			this.maxTicks = seconds * 20;
		}

		@Override
		public JsonObject tick(Minecraft mc) {
			LocalPlayer p = mc.player;
			if (mc.level.getBlockState(pos).isAir()) {
				JsonObject o = ok();
				o.addProperty("mined_after_s", ticks / 20.0);
				return o;
			}
			if (Math.sqrt(pos.distToCenterSqr(p.getEyePosition())) > REACH) return Bridge.error("too far: walk closer first");
			if (++ticks > maxTicks) {
				mc.gameMode.stopDestroyBlock();
				return Bridge.error("could not break it in time (wrong tool?)");
			}
			Direction face = faceToward(pos, p.getEyePosition());
			lookAt(p, Vec3.atCenterOf(pos));
			if (ticks == 1) mc.gameMode.startDestroyBlock(pos, face);
			else mc.gameMode.continueDestroyBlock(pos, face);
			p.swing(InteractionHand.MAIN_HAND);
			return null;
		}

		@Override
		public void cancel(Minecraft mc) {
			if (mc.gameMode != null) mc.gameMode.stopDestroyBlock();
		}
	}

	record Recipe(String[] rows, Map<Character, String> keys, int makes, boolean anyPlanks) {
		int width() {
			int w = 0;
			for (String r : rows) w = Math.max(w, r.length());
			return w;
		}

		boolean big() {
			return width() > 2 || rows.length > 2;
		}
	}

	static final Map<String, Recipe> RECIPES = new LinkedHashMap<>();

	static {
		Map<String, String> mats = Map.of("wooden", "#planks", "stone", "#cobble", "iron", "iron_ingot",
				"golden", "gold_ingot", "diamond", "diamond");
		for (var e : mats.entrySet()) {
			String x = e.getValue();
			RECIPES.put(e.getKey() + "_pickaxe", new Recipe(new String[]{"XXX", " S ", " S "}, Map.of('X', x, 'S', "stick"), 1, false));
			RECIPES.put(e.getKey() + "_axe", new Recipe(new String[]{"XX", "XS", " S"}, Map.of('X', x, 'S', "stick"), 1, false));
			RECIPES.put(e.getKey() + "_shovel", new Recipe(new String[]{"X", "S", "S"}, Map.of('X', x, 'S', "stick"), 1, false));
			RECIPES.put(e.getKey() + "_sword", new Recipe(new String[]{"X", "X", "S"}, Map.of('X', x, 'S', "stick"), 1, false));
			RECIPES.put(e.getKey() + "_hoe", new Recipe(new String[]{"XX", " S", " S"}, Map.of('X', x, 'S', "stick"), 1, false));
		}
		RECIPES.put("stick", new Recipe(new String[]{"P", "P"}, Map.of('P', "#planks"), 4, false));
		RECIPES.put("crafting_table", new Recipe(new String[]{"PP", "PP"}, Map.of('P', "#planks"), 1, false));
		RECIPES.put("chest", new Recipe(new String[]{"PPP", "P P", "PPP"}, Map.of('P', "#planks"), 1, false));
		RECIPES.put("furnace", new Recipe(new String[]{"CCC", "C C", "CCC"}, Map.of('C', "#cobble"), 1, false));
		RECIPES.put("torch", new Recipe(new String[]{"C", "S"}, Map.of('C', "#coal", 'S', "stick"), 4, false));
		RECIPES.put("planks", new Recipe(new String[]{"L"}, Map.of('L', "#log"), 4, true));
	}

	/** Shaped crafting with real inventory clicks: the 2×2 grid, or an open crafting table (opened if one is in reach). */
	static final class CraftTask implements Task {
		private final String target;
		private final Recipe recipe;
		private final int wanted;
		private int made;
		private int stage; // 0 prepare · 1 wait for the table · 2 fill the grid · 3 wait for the result · 4 clean up
		private int wait;
		private boolean openedTable;
		private String failure;

		CraftTask(String item, int count) {
			String t = item.toLowerCase().replace("minecraft:", "");
			Recipe r = RECIPES.get(t);
			if (r == null && t.endsWith("_planks")) r = RECIPES.get("planks");
			this.target = t;
			this.recipe = r;
			this.wanted = Math.max(1, count);
		}

		private boolean isTarget(String id) {
			return target.equals("planks") ? id.endsWith("_planks") : id.equals(target);
		}

		/** "oak_planks" only from oak logs; plain "planks" from any log. */
		private Predicate<String> ingredient(String key) {
			if (key.equals("#log") && !target.equals("planks")) {
				String wood = target.substring(0, target.length() - "_planks".length());
				return id -> id.matches("(stripped_)?" + Pattern.quote(wood) + "_(log|wood|stem|hyphae)");
			}
			return matcher(key);
		}

		private int gridSlot(int row, int col, boolean table) {
			return table ? 1 + row * 3 + col : 1 + row * 2 + col;
		}

		private int invFrom(boolean table) {
			return table ? 10 : 9;
		}

		private int invTo(boolean table) {
			return table ? 45 : 44;
		}

		private void click(Minecraft mc, AbstractContainerMenu menu, int slot, int button, ClickType type) {
			mc.gameMode.handleInventoryMouseClick(menu.containerId, slot, button, type, mc.player);
		}

		private void clearGrid(Minecraft mc, AbstractContainerMenu menu, boolean table) {
			int cells = table ? 9 : 4;
			for (int i = 1; i <= cells; i++)
				if (menu.getSlot(i).hasItem()) click(mc, menu, i, 0, ClickType.QUICK_MOVE);
		}

		private JsonObject finish(Minecraft mc) {
			AbstractContainerMenu menu = mc.player.containerMenu;
			boolean table = menu instanceof CraftingMenu;
			if (table || menu == mc.player.inventoryMenu) clearGrid(mc, menu, table);
			if (openedTable) mc.player.closeContainer();
			JsonObject o = failure == null ? ok() : Bridge.error(failure);
			o.addProperty("crafted", made);
			o.addProperty("item", target);
			return o;
		}

		@Override
		public JsonObject tick(Minecraft mc) {
			LocalPlayer p = mc.player;
			if (recipe == null) return Bridge.error("no recipe for " + target + "; known: " + String.join(", ", RECIPES.keySet()));
			AbstractContainerMenu menu = p.containerMenu;
			boolean table = menu instanceof CraftingMenu;
			switch (stage) {
				case 0 -> {
					if (recipe.big() && !table) {
						if (menu != p.inventoryMenu) p.closeContainer();
						JsonObject near = find(mc, "crafting_table", 5, 4, 1);
						var blocks = near.getAsJsonArray("blocks");
						if (blocks.isEmpty() || !blocks.get(0).getAsJsonObject().get("reachable").getAsBoolean())
							return Bridge.error(target + " needs a crafting table within reach: place one (place crafting_table) or walk to one");
						var at = blocks.get(0).getAsJsonObject().getAsJsonArray("pos");
						useBlock(mc, new BlockPos(at.get(0).getAsInt(), at.get(1).getAsInt(), at.get(2).getAsInt()));
						openedTable = true;
						stage = 1;
						wait = 0;
						return null;
					}
					if (!recipe.big() && !table && menu != p.inventoryMenu) p.closeContainer();
					stage = 2;
					return null;
				}
				case 1 -> {
					if (table) {
						stage = 2;
					} else if (++wait > 40) {
						return Bridge.error("the crafting table did not open");
					}
					return null;
				}
				case 2 -> {
					clearGrid(mc, menu, table);
					for (int r = 0; r < recipe.rows().length; r++) {
						String row = recipe.rows()[r];
						for (int c = 0; c < row.length(); c++) {
							char ch = row.charAt(c);
							if (ch == ' ') continue;
							Predicate<String> ing = ingredient(recipe.keys().get(ch));
							int src = -1;
							for (int s = invFrom(table); s <= invTo(table); s++) {
								ItemStack st = menu.getSlot(s).getItem();
								if (!st.isEmpty() && ing.test(itemId(st))) {
									src = s;
									break;
								}
							}
							if (src < 0) {
								failure = "missing " + recipe.keys().get(ch) + " for " + target + (made > 0 ? " after " + made : "");
								stage = 4;
								return null;
							}
							click(mc, menu, src, 0, ClickType.PICKUP);   // take the stack
							click(mc, menu, gridSlot(r, c, table), 1, ClickType.PICKUP);  // drop one into the cell
							click(mc, menu, src, 0, ClickType.PICKUP);   // put the rest back
						}
					}
					stage = 3;
					wait = 0;
					return null;
				}
				case 3 -> {
					ItemStack out = menu.getSlot(0).getItem();
					if (!out.isEmpty() && isTarget(itemId(out))) {
						int n = out.getCount();
						click(mc, menu, 0, 0, ClickType.QUICK_MOVE);
						made += n;
						stage = made >= wanted ? 4 : 2;
					} else if (++wait > 30) {
						failure = "the grid produced nothing (" + (out.isEmpty() ? "empty" : itemId(out)) + ")";
						stage = 4;
					}
					return null;
				}
				default -> {
					return finish(mc);
				}
			}
		}

		@Override
		public void cancel(Minecraft mc) {
			if (mc.player != null) finish(mc);
		}
	}
}
