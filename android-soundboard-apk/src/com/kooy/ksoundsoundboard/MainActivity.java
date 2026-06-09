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
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
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

    private static final int BG = Color.rgb(7, 10, 18);
    private static final int CARD = Color.rgb(12, 18, 30);
    private static final int PANEL = Color.rgb(8, 13, 24);
    private static final int CYAN = Color.rgb(62, 216, 255);
    private static final int MAGENTA = Color.rgb(255, 92, 199);
    private static final int TEXT = Color.rgb(236, 247, 255);
    private static final int MUTED = Color.rgb(147, 164, 184);
    private static final int DANGER = Color.rgb(255, 111, 132);

    private SharedPreferences prefs;
    private WebView webView;
    private LinearLayout root;
    private TextView status;
    private EditText pinInput;
    private Button primaryButton;
    private Button secondaryButton;
    private Button tertiaryButton;

    private String discoveredBaseUrl = "";
    private String activeWebBaseUrl = "";
    private String activeWebToken = "";
    private boolean webLoadFailureHandled = false;

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
            showConnectingUi(baseUrl, token);
            retrySavedConnection(baseUrl, token);
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

    private Button makeButton(String text, int role) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(14), dp(8), dp(14), dp(8));

        int fill = Color.rgb(18, 24, 38);
        int stroke = CYAN;
        int textColor = TEXT;

        if (role == 1) {
            fill = CYAN;
            stroke = CYAN;
            textColor = Color.rgb(7, 16, 24);
        } else if (role == 2) {
            fill = Color.rgb(36, 14, 32);
            stroke = MAGENTA;
            textColor = TEXT;
        } else if (role == 3) {
            fill = Color.rgb(34, 17, 26);
            stroke = DANGER;
            textColor = Color.rgb(255, 225, 231);
        }

        button.setTextColor(textColor);
        button.setBackground(rounded(fill, stroke, 1, 14));
        return button;
    }

    private View spacer(int heightDp) {
        View view = new View(this);
        view.setLayoutParams(new LinearLayout.LayoutParams(1, dp(heightDp)));
        return view;
    }

    private LinearLayout makeRoot() {
        webView = null;

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(14), dp(14), dp(14), dp(14));
        root.setBackgroundColor(BG);

        setContentView(root);
        immersive();
        return root;
    }

    private LinearLayout makeCard(String title, String subtitle, String message) {
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        boolean narrow = screenWidth < dp(620);

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setPadding(dp(24), dp(22), dp(24), dp(22));
        card.setBackground(rounded(CARD, CYAN, 1, 24));

        int cardWidth = Math.min(screenWidth - dp(28), dp(760));
        if (cardWidth < dp(280)) {
            cardWidth = screenWidth - dp(16);
        }

        root.addView(card, new LinearLayout.LayoutParams(cardWidth, LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView badge = makeText("K", 28, CYAN, Typeface.BOLD);
        badge.setBackground(rounded(Color.rgb(5, 8, 15), MAGENTA, 1, 18));
        badge.setPadding(dp(16), dp(8), dp(16), dp(8));
        LinearLayout.LayoutParams badgeParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        badgeParams.setMargins(0, 0, 0, dp(12));
        card.addView(badge, badgeParams);

        TextView titleView = makeText(title, narrow ? 22 : 28, TEXT, Typeface.BOLD);
        titleView.setLetterSpacing(0.08f);
        card.addView(titleView);

        TextView subtitleView = makeText(subtitle, narrow ? 12 : 14, MUTED, Typeface.NORMAL);
        subtitleView.setPadding(0, dp(6), 0, dp(16));
        card.addView(subtitleView);

        status = makeText(message, narrow ? 13 : 15, CYAN, Typeface.NORMAL);
        status.setPadding(dp(12), dp(10), dp(12), dp(10));
        status.setBackground(rounded(PANEL, Color.rgb(38, 88, 112), 1, 16));
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        statusParams.setMargins(0, 0, 0, dp(16));
        card.addView(status, statusParams);

        return card;
    }

    private void addButtonRow(LinearLayout card, Button first, Button second, Button third) {
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        boolean narrow = screenWidth < dp(620);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(narrow ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);

        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
            narrow ? LinearLayout.LayoutParams.MATCH_PARENT : dp(180),
            dp(48)
        );
        buttonParams.setMargins(dp(6), dp(4), dp(6), dp(4));

        if (first != null) {
            row.addView(first, buttonParams);
        }
        if (second != null) {
            row.addView(second, buttonParams);
        }
        if (third != null) {
            row.addView(third, buttonParams);
        }

        card.addView(row);
    }

    private void showPairingUi(String message) {
        makeRoot();

        LinearLayout card = makeCard(
            "K-SOUNDS",
            "Soundboard Remote",
            message
        );

        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        boolean narrow = screenWidth < dp(620);

        pinInput = new EditText(this);
        pinInput.setHint("6-digit PC code");
        pinInput.setSingleLine(true);
        pinInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_NORMAL);
        pinInput.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        pinInput.setPrivateImeOptions("com.google.android.inputmethod.latin.noFullscreenKeyboard=true");
        pinInput.setFilters(new InputFilter[] { new InputFilter.LengthFilter(6) });
        pinInput.setSelectAllOnFocus(true);
        pinInput.setTextColor(Color.WHITE);
        pinInput.setHintTextColor(MUTED);
        pinInput.setGravity(Gravity.CENTER);
        pinInput.setTextSize(narrow ? 20 : 22);
        pinInput.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        pinInput.setPadding(dp(14), dp(10), dp(14), dp(10));
        pinInput.setBackground(rounded(Color.rgb(5, 8, 15), MAGENTA, 1, 16));

        LinearLayout.LayoutParams pinParams = new LinearLayout.LayoutParams(
            narrow ? LinearLayout.LayoutParams.MATCH_PARENT : dp(280),
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
        pinParams.setMargins(0, 0, 0, dp(14));
        card.addView(pinInput, pinParams);

        primaryButton = makeButton("Connect", 1);
        primaryButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                pairWithPin();
            }
        });

        secondaryButton = makeButton("Search PC", 0);
        secondaryButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                discoverAndShow();
            }
        });

        tertiaryButton = null;
        addButtonRow(card, primaryButton, secondaryButton, null);

        TextView help = makeText(
            "On the PC: open K-Sounds Hub and click Pair Android, then enter the 6-digit code here.",
            narrow ? 11 : 12,
            MUTED,
            Typeface.NORMAL
        );
        help.setPadding(0, dp(14), 0, 0);
        card.addView(help);

        setPairControlsEnabled(false);
    }

    private void showConnectingUi(final String baseUrl, final String token) {
        makeRoot();

        LinearLayout card = makeCard(
            "K-SOUNDS",
            "Remote",
            "Connecting to saved PC...\n" + baseUrl
        );

        primaryButton = makeButton("Retry", 1);
        primaryButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                retrySavedConnection(baseUrl, token);
            }
        });

        secondaryButton = makeButton("Pair again", 2);
        secondaryButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startPairingWithoutForgetting();
            }
        });

        tertiaryButton = makeButton("Disconnect", 3);
        tertiaryButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                forgetSavedPc();
            }
        });

        addButtonRow(card, primaryButton, secondaryButton, tertiaryButton);
    }

    private void showServerNotFoundUi(final String baseUrl, final String token, final String reason) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                makeRoot();

                LinearLayout card = makeCard(
                    "SERVER NOT FOUND",
                    "Remote — Server not found",
                    reason
                    + "\n\nSaved PC: "
                    + (baseUrl == null || baseUrl.length() == 0 ? "none" : baseUrl)
                    + "\n\nCheck that K-Sounds Hub is running, Pair Android is active, and the phone is on the same LAN."
                );

                primaryButton = makeButton("Retry", 1);
                primaryButton.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        retrySavedConnection(baseUrl, token);
                    }
                });

                secondaryButton = makeButton("Pair again", 2);
                secondaryButton.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        startPairingWithoutForgetting();
                    }
                });

                tertiaryButton = makeButton("Disconnect", 3);
                tertiaryButton.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        forgetSavedPc();
                    }
                });

                addButtonRow(card, primaryButton, secondaryButton, tertiaryButton);
            }
        });
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
                if (primaryButton != null) {
                    primaryButton.setEnabled(enabled);
                    primaryButton.setAlpha(enabled ? 1.0f : 0.45f);
                }
            }
        });
    }

    private void setSearching(final boolean searching) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (secondaryButton != null) {
                    secondaryButton.setText(searching ? "Searching..." : "Search PC");
                    secondaryButton.setEnabled(!searching);
                    secondaryButton.setAlpha(searching ? 0.55f : 1.0f);
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

    private void clearSavedPairingAndRestart(boolean autoSearch) {
        prefs.edit()
            .remove("base_url")
            .remove("token")
            .apply();

        discoveredBaseUrl = "";
        activeWebBaseUrl = "";
        activeWebToken = "";
        webLoadFailureHandled = false;

        showPairingUi(autoSearch
            ? "Searching for K-Sounds Hub on your network..."
            : "Saved PC forgotten. Tap Search PC when you are ready."
        );

        if (autoSearch) {
            discoverAndShow();
        }
    }

    private void startPairingWithoutForgetting() {
        discoveredBaseUrl = "";
        activeWebBaseUrl = "";
        activeWebToken = "";
        webLoadFailureHandled = false;

        showPairingUi("Searching for K-Sounds Hub on your network...");
        discoverAndShow();
    }

    private void forgetSavedPc() {
        clearSavedPairingAndRestart(false);
    }

    private void retrySavedConnection(final String fallbackBaseUrl, final String token) {
        setStatus("Searching for K-Sounds Hub...");
        if (primaryButton != null) {
            primaryButton.setEnabled(false);
            primaryButton.setAlpha(0.55f);
        }

        new Thread(new Runnable() {
            @Override
            public void run() {
                String base = discoverServer();
                if (base == null || base.isEmpty()) {
                    base = fallbackBaseUrl;
                }

                final String targetBase = base;

                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (primaryButton != null) {
                            primaryButton.setEnabled(true);
                            primaryButton.setAlpha(1.0f);
                        }
                    }
                });

                if (targetBase == null || targetBase.isEmpty()) {
                    showServerNotFoundUi(
                        fallbackBaseUrl,
                        token,
                        "K-Sounds Hub could not be found on this network."
                    );
                    return;
                }

                prefs.edit().putString("base_url", targetBase).apply();

                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        showWeb(targetBase, token);
                    }
                });
            }
        }).start();
    }

    private void handleWebLoadFailure(String reason) {
        if (webLoadFailureHandled) {
            return;
        }

        webLoadFailureHandled = true;

        if (reason == null || reason.trim().length() == 0) {
            reason = "The remote page did not load.";
        }

        showServerNotFoundUi(activeWebBaseUrl, activeWebToken, reason);
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
                    setStatus("PC not found. Check Wi-Fi/LAN, K-Sounds Hub → Pair Android, and firewall UDP 8766.");
                    return;
                }

                discoveredBaseUrl = base;
                setPairControlsEnabled(true);
                setStatus("PC found: " + base + "\nEnter the 6-digit code shown by K-Sounds Hub → Pair Android.");
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

    private void pairWithPin() {
        if (pinInput == null) {
            return;
        }

        final String pin = pinInput.getText().toString().trim();

        if (pin.length() == 0) {
            setStatus("Enter the 6-digit code shown by K-Sounds Hub → Pair Android.");
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

    private boolean handleSpecialUrl(String url) {
        if (url == null) {
            return false;
        }

        if (url.startsWith("ksounds://disconnect")) {
            forgetSavedPc();
            return true;
        }

        return false;
    }

    private void showWeb(String baseUrl, String token) {
        activeWebBaseUrl = baseUrl;
        activeWebToken = token;
        webLoadFailureHandled = false;

        webView = new WebView(this);
        webView.setBackgroundColor(BG);

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

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleSpecialUrl(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request == null || request.getUrl() == null) {
                    return false;
                }
                return handleSpecialUrl(request.getUrl().toString());
            }

            @Override
            public void onReceivedError(
                WebView view,
                int errorCode,
                String description,
                String failingUrl
            ) {
                if (
                    failingUrl == null
                    || activeWebBaseUrl.length() == 0
                    || failingUrl.startsWith(activeWebBaseUrl)
                ) {
                    handleWebLoadFailure(description);
                }
            }

            @Override
            public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error
            ) {
                if (request != null && request.isForMainFrame()) {
                    String description = "The remote page did not load.";
                    if (error != null && error.getDescription() != null) {
                        description = error.getDescription().toString();
                    }
                    handleWebLoadFailure(description);
                }
            }
        });

        setContentView(webView);
        immersive();

        try {
            String url = baseUrl
                + "/?token=" + URLEncoder.encode(token, "UTF-8")
                + "&v=" + System.currentTimeMillis();
            webView.loadUrl(url);
        } catch (Exception e) {
            showServerNotFoundUi(baseUrl, token, "URL error: " + e.getMessage());
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
