package it.atlante.app;

/** Un'unica schermata: quale Atlante apre lo decide la versione (cinema o serie) con cui è stata costruita. */
public class MainActivity extends AtlasActivity {
    @Override protected String appPath() { return BuildConfig.APP_PATH; }
}
