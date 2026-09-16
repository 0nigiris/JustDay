---
name: minecraft
description: Play Minecraft Java as the user's own character through the JustDay Bridge mod — see position, blocks, inventory; walk and mine with Baritone; craft, place, use blocks. Survival goals like "get stone tools", "добудь дерево", "скрафти кирку", "иди к …".
---

# Minecraft (JustDay Bridge + Baritone)

The game must be running with the bridge mod (Fabric 1.21.10). `justday mc ping` → `{"in_world": true}`. Not installed → tell the user to run `~/JustDay/minecraft/install.sh` and restart Minecraft (don't do it mid-game yourself).

Everything is a text command — **no screenshots needed** for Minecraft; use `look` only if the bridge can't answer.
Every command prints JSON; `ok:false` + `error` explains what went wrong. Long actions return a `state` with position, health and inventory.

| Command | What it does |
|---|---|
| `justday mc state` | position, facing, health/food, time (`night`), `singleplayer`, hotbar, whole inventory, what the crosshair points at, hostile mobs within 24, Baritone status |
| `justday mc find block='#log' radius=48 limit=5` | nearest loaded blocks: exact id (`stone`, `crafting_table`), glob (`*_ore`), or `#log` `#planks` `#cobble` `#coal`; comma = several |
| `justday mc baritone command="mine 6 oak_log"` | any Baritone command without `#`: `mine N block…`, `goto X Y Z`, `goto crafting_table` (walks next to the nearest one), `follow player NAME`, `explore`, `come`, `surface`, `farm` |
| `justday mc wait timeout=90` | blocks until Baritone is done (or `still_running` after the timeout — check `state.inventory` and call again or `stop`) |
| `justday mc stop` | stop Baritone and any bridge action |
| `justday mc craft item=wooden_pickaxe count=1` | real inventory clicks; 2×2 in the inventory, 3×3 needs a crafting table **within 4.5 blocks** (opened automatically). Knows: `planks` (any log) / `oak_planks`…, `stick`, `crafting_table`, `chest`, `furnace`, `torch`, `{wooden,stone,iron,golden,diamond}_{pickaxe,axe,shovel,sword,hoe}`. `count` = items wanted |
| `justday mc place item=crafting_table` | places next to the player (or at `x= y= z=`); answer has the `pos` — remember it |
| `justday mc use x= y= z=` | right-click a block in reach (open a table/chest/furnace, press a button) |
| `justday mc mine x= y= z=` | break one block in reach with the held item (Baritone's `mine` is usually better) |
| `justday mc select item=stone_pickaxe` | hold an item (swaps it into the hotbar if needed) |
| `justday mc look x= y= z=` / `look yaw= pitch=` · `close` | aim · close an open screen |

## Rules
- `state.singleplayer` is false (a server) → ask the user before using Baritone: many servers ban it.
- Never type in chat, never attack players, never break things the user built (houses, chests, farms) — mine natural blocks. Don't use `mine` on `*_planks`, `glass`, `chest`, `bed`.
- Say short progress lines only at milestones ("Дерево есть, делаю кирку"); the user watches the game.
- Health ≤ 8, or `hostiles` close at night → `stop`, tell the user, suggest sleeping / waiting / retreating (`baritone command="surface"`).
- Baritone breaks and places blocks on its own to path; that is normal in the wild.

## Recipe: stone tools from nothing (≈ 3–6 min)
1. `state` — note inventory, `night`, `hostiles`.
2. **Wood.** `find block='#log' radius=64 limit=3` → take the nearest id (e.g. `birch_log`) → `baritone command="mine 6 birch_log"` → `wait timeout=120`. Repeat `wait` while `still_running`; if no logs are loaded nearby → `baritone command="explore"` for ~20 s, `stop`, `find` again.
3. **Planks & sticks.** `craft item=planks count=24` (4 per log) → `craft item=stick count=12` (wooden pickaxe 2 + stone tools 7, with a spare).
4. **Table.** `craft item=crafting_table` → `place item=crafting_table` → remember its `pos`.
5. **Wooden pickaxe.** `craft item=wooden_pickaxe` (the table is in reach right after placing).
6. **Stone.** `select item=wooden_pickaxe` → `baritone command="mine stone"` (stone drops `cobblestone`) → loop `wait timeout=20` and read `state.inventory.cobblestone`; at ≥ 11 → `stop`. No stone loaded nearby → `find block=stone radius=32 height=24`, `goto` next to the nearest one, then mine. Don't mine andesite/diorite/granite: they don't count as cobblestone.
7. **Back to the table.** `baritone command="goto crafting_table"` → `wait`. (Or `craft item=crafting_table` + `place` if it's far and you have 4 planks.)
8. **Stone tools.** `craft item=stone_pickaxe`, `stone_axe`, `stone_shovel`, `stone_sword` (needs 3+3+1+2 = 9 cobblestone and 7 sticks). Missing something → the error says what.
9. `select item=stone_pickaxe`, `state`, report in one sentence what was made.

Learned something about this world (base coordinates, where the table is, which biome) → save it to memory for next time.
