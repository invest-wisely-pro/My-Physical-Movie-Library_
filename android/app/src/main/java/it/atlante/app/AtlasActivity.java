package it.atlante.app;

import android.app.Activity;
import android.app.UiModeManager;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.KeyEvent;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/** Contenitore comune: apre uno degli Atlanti (pagina web su GitHub Pages) a schermo intero. */
public abstract class AtlasActivity extends Activity {
    /** Cartella dell'Atlante dentro il sito, per esempio "atlante/" o "serie/". */
    protected abstract String appPath();

    private static final int REQ_FILE = 71;
    private WebView web;
    private ValueCallback<Uri[]> chooser;
    private String home;
    private boolean tv;

    private static final String OFFLINE_HTML =
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        + "<body style='margin:0;background:#0F1416;color:#ECE7DC;font-family:sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center'>"
        + "<div style='padding:24px'><h2>Nessuna connessione</h2><p>Alla prima apertura serve internet. Dopo, l'Atlante funziona anche offline.</p>"
        + "<button style='font-size:20px;padding:12px 28px;border:0;border-radius:10px;background:#E9A23B' onclick='AtlanteApp.retry()'>Riprova</button></div></body></html>";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        UiModeManager um = (UiModeManager) getSystemService(UI_MODE_SERVICE);
        tv = (um != null && um.getCurrentModeType() == Configuration.UI_MODE_TYPE_TELEVISION)
            || getPackageManager().hasSystemFeature("android.software.leanback");
        home = BuildConfig.BASE_URL + appPath() + (tv ? "?tv=1" : "");   // ?tv=1 accende la modalità TV dell'Atlante

        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // abilita anche IndexedDB: qui sta la tua collezione
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setAllowFileAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " AtlanteApp/" + BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setBackgroundColor(0xFF0F1416);
        web.addJavascriptInterface(new Bridge(), "AtlanteApp");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener((url, ua, cd, mime, len) -> download(url, URLUtil.guessFileName(url, cd, mime), mime));
        web.setFocusable(true);
        web.requestFocus();
        if (state != null) web.restoreState(state); else web.loadUrl(home);
    }

    private boolean isOwn(String url) { return url != null && url.startsWith(BuildConfig.BASE_URL); }

    private void openExternal(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (ActivityNotFoundException e) { toast("Nessuna app per aprire questo collegamento"); }
    }

    private void toast(String m) { runOnUiThread(() -> Toast.makeText(this, m, Toast.LENGTH_LONG).show()); }

    /** I backup dell'Atlante sono file "blob:" o "data:": il WebView da solo non li salva, qui finiscono in Download. */
    private void download(String url, String name, String mime) {
        if (url.startsWith("blob:")) {
            String js = "(async()=>{try{const r=await fetch(" + JSONq(url) + ");const b=await r.blob();const f=new FileReader();"
                + "f.onloadend=()=>AtlanteApp.save(" + JSONq(name) + "," + JSONq(mime == null ? "application/octet-stream" : mime) + ",String(f.result).split(',')[1]);"
                + "f.readAsDataURL(b);}catch(e){AtlanteApp.fail(String(e));}})()";
            web.evaluateJavascript(js, null);
        } else if (url.startsWith("data:")) {
            int c = url.indexOf(',');
            if (c > 0 && url.substring(0, c).contains("base64")) saveBytes(name, mime, Base64.decode(url.substring(c + 1), Base64.DEFAULT));
            else if (c > 0) saveBytes(name, mime, Uri.decode(url.substring(c + 1)).getBytes());
        } else {
            openExternal(url);
        }
    }

    private static String JSONq(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ") + "\"";
    }

    private void saveBytes(String name, String mime, byte[] data) {
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                v.put(MediaStore.Downloads.MIME_TYPE, mime == null ? "application/octet-stream" : mime);
                v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                Uri u = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (u == null) throw new Exception("insert");
                try (OutputStream o = getContentResolver().openOutputStream(u)) { o.write(data); }
                toast("Salvato in Download: " + name);
            } else {
                File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);   // Android 9 e prima: cartella dell'app, senza permessi
                File f = new File(dir, name);
                try (FileOutputStream o = new FileOutputStream(f)) { o.write(data); }
                toast("Salvato in: " + f.getAbsolutePath());
            }
        } catch (Exception e) {
            toast("Salvataggio non riuscito");
        }
    }

    /** Ponte JavaScript → Android (nome "AtlanteApp"). */
    private class Bridge {
        @JavascriptInterface public void save(String name, String mime, String b64) { saveBytes(name, mime, Base64.decode(b64, Base64.DEFAULT)); }
        @JavascriptInterface public void fail(String why) { toast("Salvataggio non riuscito"); }
        @JavascriptInterface public void retry() { runOnUiThread(() -> web.loadUrl(home)); }
    }

    private class Client extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
            String u = r.getUrl().toString();
            if (isOwn(u)) return false;       // i tuoi Atlanti restano nell'app
            openExternal(u);                  // tutto il resto (IMDb, Wikipedia, ...) si apre nel browser o nell'app giusta
            return true;
        }
        @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
            if (r.isForMainFrame()) v.loadDataWithBaseURL("https://offline.invalid/", OFFLINE_HTML, "text/html", "utf-8", null);
        }
    }

    private class Chrome extends WebChromeClient {
        @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
            if (chooser != null) chooser.onReceiveValue(null);
            chooser = cb;
            try { startActivityForResult(p.createIntent(), REQ_FILE); }
            catch (Exception e) { chooser = null; toast("Impossibile scegliere il file"); return false; }
            return true;
        }
    }

    @Override protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_FILE && chooser != null) { chooser.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data)); chooser = null; }
        else super.onActivityResult(req, res, data);
    }

    @Override public boolean onKeyDown(int code, KeyEvent e) {
        if (code == KeyEvent.KEYCODE_BACK && web.canGoBack()) { web.goBack(); return true; }   // Indietro: pagina precedente, poi chiude
        return super.onKeyDown(code, e);
    }

    @Override protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }
    @Override protected void onPause() { super.onPause(); web.onPause(); CookieManager.getInstance().flush(); }
    @Override protected void onResume() { super.onResume(); web.onResume(); }
    @Override protected void onDestroy() { if (web != null) { web.destroy(); } super.onDestroy(); }
}
