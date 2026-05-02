package com.kooy.ksoundsoundboard;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.net.URLEncoder;

public class MainActivity extends Activity {
    private static final int DISCOVERY_PORT = 8766;
    private static final String DISCOVERY_REQUEST = "KSH_DISCOVER_V1";
    private static final String EXPECTED_SERVICE = "KSH_SOUNDBOARD";

    private SharedPreferences prefs;
    private WebView webView;
    private LinearLayout root;
    private TextView status;
    private EditText pinInput;
    private Button pairButton;
    private Button searchButton;

    private String discoveredBaseUrl = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(
            WindowManager.LayoutParams.FLAG_FULLSCREEN,
            WindowManager.LayoutParams.FLAG_FULLSCREEN
        );
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        prefs = getSharedPreferences("ksound_pairing", MODE_PRIVATE);
        immersive();

        String token = prefs.getString("token", "");
        String baseUrl = prefs.getString("base_url", "");

        if (!token.isEmpty() && !baseUrl.isEmpty()) {
            showWeb(baseUrl, token);
            rediscoverInBackgroundAndUpdate(token);
        } else {
            showPairingUi("Recherche de K-Sound Hub sur le réseau...");
            discoverAndShow();
        }
    }

    private void showPairingUi(String message) {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(40, 40, 40, 40);
        root.setBackgroundColor(Color.rgb(7, 10, 18));

        TextView title = new TextView(this);
        title.setText("K-SOUND SOUNDBOARD");
        title.setTextColor(Color.rgb(236, 247, 255));
        title.setTextSize(26);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, 18);
        root.addView(title);

        status = new TextView(this);
        status.setText(message);
        status.setTextColor(Color.rgb(147, 164, 184));
        status.setTextSize(16);
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, 0, 0, 20);
        root.addView(status);

        pinInput = new EditText(this);
        pinInput.setHint("Code pairing PC");
        pinInput.setSingleLine(true);
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(Color.rgb(147, 164, 184));
        pinInput.setGravity(Gravity.CENTER);
        pinInput.setTextSize(22);
        root.addView(pinInput);

        pairButton = new Button(this);
        pairButton.setText("PAIR");
        pairButton.setOnClickListener(v -> pairWithPin());
        root.addView(pairButton);

        searchButton = new Button(this);
        searchButton.setText("RECHERCHER LE PC");
        searchButton.setOnClickListener(v -> discoverAndShow());
        root.addView(searchButton);

        setContentView(root);
        immersive();
    }

    private void setStatus(String text) {
        runOnUiThread(() -> {
            if (status != null) {
                status.setText(text);
            }
        });
    }

    private void discoverAndShow() {
        setStatus("Recherche UDP de K-Sound Hub...");
        new Thread(() -> {
            String base = discoverServer();
            if (base == null || base.isEmpty()) {
                setStatus("PC introuvable. Vérifie le Wi-Fi/LAN, le service web et le firewall UDP 8766.");
                return;
            }

            discoveredBaseUrl = base;
            setStatus("PC trouvé: " + base + "\nLance `ksound-soundboard-pair` sur le PC puis entre le code.");
        }).start();
    }

    private String discoverServer() {
        DatagramSocket socket = null;
        try {
            socket = new DatagramSocket();
            socket.setBroadcast(true);
            socket.setSoTimeout(2500);

            byte[] out = DISCOVERY_REQUEST.getBytes("UTF-8");
            DatagramPacket packet = new DatagramPacket(
                out,
                out.length,
                InetAddress.getByName("255.255.255.255"),
                DISCOVERY_PORT
            );
            socket.send(packet);

            byte[] buf = new byte[2048];
            DatagramPacket response = new DatagramPacket(buf, buf.length);
            socket.receive(response);

            String body = new String(response.getData(), 0, response.getLength(), "UTF-8");
            JSONObject json = new JSONObject(body);

            if (!EXPECTED_SERVICE.equals(json.optString("service", ""))) {
                return "";
            }

            int port = json.optInt("http_port", 8765);
            String host = response.getAddress().getHostAddress();

            return "http://" + host + ":" + port;
        } catch (Exception e) {
            return "";
        } finally {
            if (socket != null) {
                socket.close();
            }
        }
    }

    private void rediscoverInBackgroundAndUpdate(String token) {
        new Thread(() -> {
            String base = discoverServer();
            if (base != null && !base.isEmpty()) {
                prefs.edit().putString("base_url", base).apply();
            }
        }).start();
    }

    private void pairWithPin() {
        String pin = pinInput.getText().toString().trim();

        if (pin.length() == 0) {
            setStatus("Entre le code affiché par `ksound-soundboard-pair`.");
            return;
        }

        if (discoveredBaseUrl == null || discoveredBaseUrl.isEmpty()) {
            setStatus("PC pas encore trouvé. Appuie sur RECHERCHER LE PC.");
            return;
        }

        setStatus("Pairing en cours...");

        new Thread(() -> {
            try {
                String encodedPin = URLEncoder.encode(pin, "UTF-8");
                URL url = new URL(discoveredBaseUrl + "/api/pair?pin=" + encodedPin);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(2500);
                conn.setReadTimeout(2500);
                conn.setRequestMethod("GET");

                int code = conn.getResponseCode();
                BufferedReader reader = new BufferedReader(new InputStreamReader(
                    code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream()
                ));

                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }

                JSONObject json = new JSONObject(sb.toString());
                if (code >= 200 && code < 300 && json.optBoolean("ok", false)) {
                    String token = json.optString("token", "");
                    if (token.isEmpty()) {
                        setStatus("Pairing OK mais token vide.");
                        return;
                    }

                    prefs.edit()
                        .putString("base_url", discoveredBaseUrl)
                        .putString("token", token)
                        .apply();

                    runOnUiThread(() -> showWeb(discoveredBaseUrl, token));
                } else {
                    setStatus(json.optString("error", "Pairing refusé."));
                }
            } catch (Exception e) {
                setStatus("Erreur pairing: " + e.getMessage());
            }
        }).start();
    }

    private void showWeb(String baseUrl, String token) {
        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(7, 10, 18));

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        // Always reload the current PC web UI. The soundboard UI lives on the
        // K-Sound Hub web server, so stale WebView cache can hide UI changes.
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.clearCache(true);
        webView.clearHistory();
        WebStorage.getInstance().deleteAllData();

        webView.setWebViewClient(new WebViewClient());
        setContentView(webView);
        immersive();

        try {
            String url = baseUrl
                + "/?token=" + URLEncoder.encode(token, "UTF-8")
                + "&v=" + System.currentTimeMillis();
            webView.loadUrl(url);
        } catch (Exception e) {
            showPairingUi("Erreur URL: " + e.getMessage());
        }
    }

    private void immersive() {
        View decor = getWindow().getDecorView();
        decor.setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            | View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        );
    }

    @Override
    protected void onResume() {
        super.onResume();
        immersive();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            immersive();
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
