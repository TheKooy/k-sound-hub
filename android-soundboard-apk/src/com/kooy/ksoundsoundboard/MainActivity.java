package com.kooy.ksoundsoundboard;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
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
    private static final String DISCOVERY_REQUEST = "KSH_DISCOVER_V2";
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
            showPairingUi("Searching for K-Sounds Hub on your network...");
            discoverAndShow();
        }
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private GradientDrawable rounded(int color, int strokeColor, int strokeDp, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radiusDp));
        if (strokeDp > 0) {
            drawable.setStroke(dp(strokeDp), strokeColor);
        }
        return drawable;
    }

    private TextView makeText(String text, int sizeSp, int color, int style) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color);
        view.setTextSize(sizeSp);
        view.setTypeface(Typeface.DEFAULT, style);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private Button makeButton(String text, boolean primary) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setTextColor(primary ? Color.rgb(7, 16, 24) : Color.rgb(236, 247, 255));
        button.setPadding(dp(14), dp(8), dp(14), dp(8));
        button.setBackground(
            rounded(
                primary ? Color.rgb(62, 216, 255) : Color.rgb(18, 24, 38),
                primary ? Color.rgb(62, 216, 255) : Color.rgb(62, 216, 255),
                1,
                14
            )
        );
        return button;
    }

    private void showPairingUi(String message) {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(14), dp(14), dp(14), dp(14));
        root.setBackgroundColor(Color.rgb(7, 10, 18));

        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        boolean narrow = screenWidth < dp(620);

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setPadding(dp(24), dp(22), dp(24), dp(22));
        card.setBackground(
            rounded(
                Color.rgb(12, 18, 30),
                Color.rgb(62, 216, 255),
                1,
                24
            )
        );

        int cardWidth = Math.min(screenWidth - dp(28), dp(760));
        if (cardWidth < dp(280)) {
            cardWidth = screenWidth - dp(16);
        }
        root.addView(card, new LinearLayout.LayoutParams(cardWidth, LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView title = makeText("K-SOUND SOUNDBOARD", narrow ? 22 : 28, Color.rgb(236, 247, 255), Typeface.BOLD);
        title.setLetterSpacing(0.08f);
        card.addView(title);

        TextView subtitle = makeText(
            "Local Android remote for your K-Sounds Hub soundboard.",
            narrow ? 12 : 14,
            Color.rgb(147, 164, 184),
            Typeface.NORMAL
        );
        subtitle.setPadding(0, dp(6), 0, dp(16));
        card.addView(subtitle);

        status = makeText(message, narrow ? 13 : 15, Color.rgb(62, 216, 255), Typeface.NORMAL);
        status.setPadding(dp(12), dp(10), dp(12), dp(10));
        status.setBackground(
            rounded(
                Color.rgb(8, 13, 24),
                Color.rgb(38, 88, 112),
                1,
                16
            )
        );
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        statusParams.setMargins(0, 0, 0, dp(16));
        card.addView(status, statusParams);

        pinInput = new EditText(this);
        pinInput.setHint("6-digit PC code");
        pinInput.setSingleLine(true);
        pinInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_NORMAL);
        pinInput.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        pinInput.setPrivateImeOptions("com.google.android.inputmethod.latin.noFullscreenKeyboard=true");
        pinInput.setFilters(new InputFilter[] { new InputFilter.LengthFilter(6) });
        pinInput.setSelectAllOnFocus(true);
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(Color.rgb(147, 164, 184));
        pinInput.setGravity(Gravity.CENTER);
        pinInput.setTextSize(narrow ? 20 : 22);
        pinInput.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        pinInput.setPadding(dp(14), dp(10), dp(14), dp(10));
        pinInput.setBackground(
            rounded(
                Color.rgb(5, 8, 15),
                Color.rgb(255, 92, 199),
                1,
                16
            )
        );

        LinearLayout.LayoutParams pinParams = new LinearLayout.LayoutParams(
            narrow ? LinearLayout.LayoutParams.MATCH_PARENT : dp(280),
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        pinParams.setMargins(0, 0, 0, dp(14));
        card.addView(pinInput, pinParams);

        LinearLayout buttonRow = new LinearLayout(this);
        buttonRow.setOrientation(narrow ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        buttonRow.setGravity(Gravity.CENTER);

        pairButton = makeButton("Connect", true);
        pairButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                pairWithPin();
            }
        });

        searchButton = makeButton("Search PC", false);
        searchButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                discoverAndShow();
            }
        });

        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
            narrow ? LinearLayout.LayoutParams.MATCH_PARENT : dp(180),
            dp(48)
        );
        buttonParams.setMargins(dp(6), dp(4), dp(6), dp(4));

        buttonRow.addView(pairButton, buttonParams);
        buttonRow.addView(searchButton, buttonParams);
        card.addView(buttonRow);

        TextView help = makeText(
            "On the PC: run `ksound-soundboard-pair`, then enter the code here.",
            narrow ? 11 : 12,
            Color.rgb(147, 164, 184),
            Typeface.NORMAL
        );
        help.setPadding(0, dp(14), 0, 0);
        card.addView(help);

        setContentView(root);
        setPairControlsEnabled(false);
        immersive();
    }

    private JSONObject tryParseJson(String text) {
        try {
            return new JSONObject(text);
        } catch (Exception e) {
            return null;
        }
    }

    private void setPairControlsEnabled(final boolean enabled) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (pairButton != null) {
                    pairButton.setEnabled(enabled);
                    pairButton.setAlpha(enabled ? 1.0f : 0.45f);
                }
            }
        });
    }

    private void setSearching(final boolean searching) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (searchButton != null) {
                    searchButton.setText(searching ? "Searching..." : "Search PC");
                    searchButton.setEnabled(!searching);
                    searchButton.setAlpha(searching ? 0.55f : 1.0f);
                }
            }
        });
    }

    private void focusPinInput() {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (pinInput == null) {
                    return;
                }

                pinInput.requestFocus();
                pinInput.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                        if (imm != null) {
                            imm.showSoftInput(pinInput, InputMethodManager.SHOW_IMPLICIT);
                        }
                    }
                }, 180);
            }
        });
    }

    private void setStatus(final String text) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (status != null) {
                    status.setText(text);
                }
            }
        });
    }

    private void discoverAndShow() {
        setPairControlsEnabled(false);
        setSearching(true);
        setStatus("Searching for K-Sounds Hub on your LAN...");

        new Thread(new Runnable() {
            @Override
            public void run() {
                String base = discoverServer();
                setSearching(false);

                if (base == null || base.isEmpty()) {
                    discoveredBaseUrl = "";
                    setStatus("PC not found. Check Wi-Fi/LAN, the web service, and firewall UDP 8766.");
                    return;
                }

                discoveredBaseUrl = base;
                setPairControlsEnabled(true);
                setStatus("PC found: " + base + "\nRun `ksound-soundboard-pair` on the PC, then enter the 6-digit code.");
                focusPinInput();
            }
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
        new Thread(new Runnable() {
            @Override
            public void run() {
                String base = discoverServer();
                if (base != null && !base.isEmpty()) {
                    prefs.edit().putString("base_url", base).apply();
                }
            }
        }).start();
    }

    private void pairWithPin() {
        final String pin = pinInput.getText().toString().trim();

        if (pin.length() == 0) {
            setStatus("Enter the 6-digit code shown by `ksound-soundboard-pair`.");
            focusPinInput();
            return;
        }

        if (!pin.matches("[0-9]+")) {
            setStatus("The pairing code must contain digits only.");
            focusPinInput();
            return;
        }

        if (discoveredBaseUrl == null || discoveredBaseUrl.isEmpty()) {
            setStatus("PC not found yet. Tap Search PC.");
            return;
        }

        setStatus("Pairing with PC...");
        setPairControlsEnabled(false);

        new Thread(new Runnable() {
            @Override
            public void run() {
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

                    String responseText = sb.toString();
                    JSONObject json = tryParseJson(responseText);

                    if (code >= 200 && code < 300 && json != null && json.optBoolean("ok", false)) {
                        String token = json.optString("token", "");
                        if (token.isEmpty()) {
                            setStatus("Pairing succeeded, but the token is empty.");
                            setPairControlsEnabled(true);
                            return;
                        }

                        prefs.edit()
                            .putString("base_url", discoveredBaseUrl)
                            .putString("token", token)
                            .apply();

                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                showWeb(discoveredBaseUrl, prefs.getString("token", ""));
                            }
                        });
                    } else {
                        String msg;
                        if (json != null) {
                            msg = json.optString("error", "Pairing refused.");
                        } else if (responseText != null && responseText.trim().length() > 0) {
                            msg = responseText.trim();
                        } else {
                            msg = "HTTP " + code;
                        }

                        setStatus("Pairing failed: " + msg);
                        setPairControlsEnabled(true);
                    }
                } catch (Exception e) {
                    setStatus("Pairing error: " + e.getMessage());
                    setPairControlsEnabled(true);
                }
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
            showPairingUi("URL error: " + e.getMessage());
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
