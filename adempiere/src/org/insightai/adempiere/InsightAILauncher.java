package org.insightai.adempiere;

import java.awt.Desktop;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Properties;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.compiere.process.SvrProcess;
import org.compiere.util.AdempiereUserError;
import org.compiere.util.Env;
import org.compiere.util.Ini;

/**
 * Opens the InsightAI dashboard for the user and role currently logged in to ADempiere.
 *
 * The process signs "user:role:time:nonce" with the key in ADEMPIERE_HOME/insightai-launcher.properties,
 * asks the InsightAI service for a one-time launch URL and opens it in the default browser.
 * It reads nothing from and writes nothing to ADempiere business data, and runs no model.
 */
public class InsightAILauncher extends SvrProcess {

	/** File in ADEMPIERE_HOME holding the service address and the shared launch key. */
	public static final String CONFIG_FILE = "insightai-launcher.properties";
	private static final int TIMEOUT_MS = 5000;
	private static final Pattern URL_FIELD = Pattern.compile("\"url\"\\s*:\\s*\"([^\"]+)\"");
	private static final Pattern DETAIL_FIELD = Pattern.compile("\"detail\"\\s*:\\s*\"([^\"]+)\"");

	@Override
	protected void prepare() {
		// no parameters
	}

	@Override
	protected String doIt() throws Exception {
		String launchUrl = requestLaunchUrl(getAD_User_ID(), Env.getAD_Role_ID(getCtx()), false);

		boolean openBrowser = Ini.isClient() && !Boolean.getBoolean("insightai.nobrowser")
				&& Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE);
		if (openBrowser) {
			Desktop.getDesktop().browse(new URI(launchUrl));
			return "InsightAI opened in your browser.";
		}
		// Web client or no desktop: the link is valid once, for one minute
		return "Open this link within one minute: " + launchUrl;
	}

	/**
	 * One-time launch URL for this user and role, using the address and key in ADEMPIERE_HOME.
	 * With embedded = true the page is told it is shown inside an ADempiere window.
	 */
	public static String requestLaunchUrl(int userId, int roleId, boolean embedded) throws Exception {
		Properties config = loadConfig();
		String serviceUrl = config.getProperty("url", "").trim();
		String key = config.getProperty("key", "").trim();
		if (serviceUrl.isEmpty() || key.isEmpty())
			throw new AdempiereUserError("InsightAI is not set up: " + CONFIG_FILE + " needs both url and key.");
		String url = requestLaunchUrl(serviceUrl, key, userId, roleId);
		return embedded ? url + "&embedded=1" : url;
	}

	private static Properties loadConfig() throws AdempiereUserError {
		File file = new File(Ini.getAdempiereHome(), CONFIG_FILE);
		Properties config = new Properties();
		try (InputStream in = new FileInputStream(file)) {
			config.load(in);
		} catch (IOException e) {
			throw new AdempiereUserError("InsightAI is not set up: " + file.getPath() + " was not found.");
		}
		return config;
	}

	/** Asks the service at serviceUrl for a one-time launch URL for this user and role. */
	public static String requestLaunchUrl(String serviceUrl, String key, int userId, int roleId) throws Exception {
		long timestamp = System.currentTimeMillis() / 1000L;
		String nonce = UUID.randomUUID().toString().replace("-", "");
		String signature = hmacSha256Hex(key, userId + ":" + roleId + ":" + timestamp + ":" + nonce);
		String body = "{\"user_id\":" + userId + ",\"role_id\":" + roleId + ",\"timestamp\":" + timestamp
				+ ",\"nonce\":\"" + nonce + "\",\"signature\":\"" + signature + "\"}";

		String base = serviceUrl.endsWith("/") ? serviceUrl.substring(0, serviceUrl.length() - 1) : serviceUrl;
		HttpURLConnection connection;
		int status;
		String response;
		try {
			connection = (HttpURLConnection) new URL(base + "/auth/launch-token").openConnection();
			connection.setConnectTimeout(TIMEOUT_MS);
			connection.setReadTimeout(TIMEOUT_MS);
			connection.setRequestMethod("POST");
			connection.setRequestProperty("Content-Type", "application/json");
			connection.setRequestProperty("Accept", "application/json");
			connection.setDoOutput(true);
			try (OutputStream out = connection.getOutputStream()) {
				out.write(body.getBytes(StandardCharsets.UTF_8));
			}
			status = connection.getResponseCode();
			response = read(status < 400 ? connection.getInputStream() : connection.getErrorStream());
		} catch (ConnectException | SocketTimeoutException e) {
			throw new AdempiereUserError("The InsightAI service is not running at " + base
					+ ". Start it with scripts\\run_service.ps1 and try again.");
		}

		if (status == 200) {
			Matcher url = URL_FIELD.matcher(response);
			if (url.find())
				return url.group(1);
			throw new AdempiereUserError("The InsightAI service gave an unexpected reply.");
		}
		Matcher detail = DETAIL_FIELD.matcher(response);
		throw new AdempiereUserError("InsightAI could not be opened: "
				+ (detail.find() ? detail.group(1).replace("\\\\", "\\") : "the service answered HTTP " + status));
	}

	static String hmacSha256Hex(String key, String message) throws Exception {
		Mac mac = Mac.getInstance("HmacSHA256");
		mac.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
		StringBuilder hex = new StringBuilder();
		for (byte b : mac.doFinal(message.getBytes(StandardCharsets.UTF_8)))
			hex.append(String.format("%02x", b));
		return hex.toString();
	}

	private static String read(InputStream in) throws IOException {
		if (in == null)
			return "";
		ByteArrayOutputStream out = new ByteArrayOutputStream();
		byte[] buffer = new byte[4096];
		for (int n; (n = in.read(buffer)) != -1;)
			out.write(buffer, 0, n);
		return new String(out.toByteArray(), StandardCharsets.UTF_8);
	}
}
