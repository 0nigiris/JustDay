package dev.justday.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * JustDay ↔ Minecraft. A Unix socket (owner-only) in $XDG_RUNTIME_DIR takes one JSON request per connection
 * and answers with one JSON line. Nothing happens in the game unless JustDay sends a command; no chat is ever sent.
 */
public class Bridge implements ClientModInitializer {
	static final Logger LOG = LoggerFactory.getLogger("justday-bridge");
	static final Gson GSON = new Gson();

	@Override
	public void onInitializeClient() {
		ClientTickEvents.END_CLIENT_TICK.register(Actions::tick);
		Thread t = new Thread(Bridge::serve, "justday-bridge");
		t.setDaemon(true);
		t.start();
	}

	static Path socketPath() {
		String dir = System.getenv("XDG_RUNTIME_DIR");
		if (dir == null || dir.isEmpty()) dir = System.getProperty("java.io.tmpdir");
		return Path.of(dir, "justday-minecraft.sock");
	}

	private static void serve() {
		Path path = socketPath();
		try {
			Files.deleteIfExists(path);
			ServerSocketChannel server = ServerSocketChannel.open(StandardProtocolFamily.UNIX);
			server.bind(UnixDomainSocketAddress.of(path));
			Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rw-------"));
			path.toFile().deleteOnExit();
			LOG.info("JustDay bridge listening on {}", path);
			while (true) {
				SocketChannel client = server.accept();
				Thread h = new Thread(() -> handle(client), "justday-bridge-client");
				h.setDaemon(true);
				h.start();
			}
		} catch (IOException e) {
			LOG.error("JustDay bridge stopped", e);
		}
	}

	private static void handle(SocketChannel ch) {
		try (ch) {
			BufferedReader in = new BufferedReader(new InputStreamReader(Channels.newInputStream(ch), StandardCharsets.UTF_8));
			String line = in.readLine();
			JsonObject reply;
			try {
				JsonObject req = JsonParser.parseString(line == null ? "{}" : line).getAsJsonObject();
				reply = dispatch(req);
			} catch (Exception e) {
				reply = error(e.getClass().getSimpleName() + ": " + e.getMessage());
			}
			ch.write(ByteBuffer.wrap((GSON.toJson(reply) + "\n").getBytes(StandardCharsets.UTF_8)));
		} catch (IOException e) {
			LOG.debug("client gone", e);
		}
	}

	static JsonObject error(String msg) {
		JsonObject o = new JsonObject();
		o.addProperty("ok", false);
		o.addProperty("error", msg);
		return o;
	}

	private static JsonObject dispatch(JsonObject req) throws Exception {
		String cmd = req.has("cmd") ? req.get("cmd").getAsString() : "state";
		Minecraft mc = Minecraft.getInstance();
		if (cmd.equals("ping")) {
			JsonObject o = new JsonObject();
			o.addProperty("ok", true);
			o.addProperty("in_world", mc.player != null);
			return o;
		}
		// long actions: the command starts a task on the game thread and waits for it here
		long timeout = req.has("timeout") ? req.get("timeout").getAsLong() : 60;
		CompletableFuture<JsonObject> done = new CompletableFuture<>();
		mc.execute(() -> {
			try {
				if (mc.player == null || mc.level == null) {
					done.complete(error("not in a world"));
					return;
				}
				Actions.start(cmd, req, done);
			} catch (Exception e) {
				done.complete(error(e.getClass().getSimpleName() + ": " + e.getMessage()));
			}
		});
		try {
			return done.get(timeout + 5, TimeUnit.SECONDS);
		} catch (java.util.concurrent.TimeoutException e) {
			mc.execute(Actions::abort);
			return error("timeout after " + timeout + " s (action stopped)");
		}
	}
}
