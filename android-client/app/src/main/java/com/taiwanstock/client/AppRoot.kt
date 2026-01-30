package com.taiwanstock.client

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

private enum class Tab { Watchlist, Alerts, Settings }

@Composable
fun AppRoot() {
    val context = LocalContext.current

    var tab by remember { mutableStateOf(Tab.Watchlist) }
    var settings by remember { mutableStateOf(loadSettings(context)) }

    MaterialTheme {
        Scaffold(
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(
                        selected = tab == Tab.Watchlist,
                        onClick = { tab = Tab.Watchlist },
                        label = { Text("Watchlist") },
                        icon = {}
                    )
                    NavigationBarItem(
                        selected = tab == Tab.Alerts,
                        onClick = { tab = Tab.Alerts },
                        label = { Text("Alerts") },
                        icon = {}
                    )
                    NavigationBarItem(
                        selected = tab == Tab.Settings,
                        onClick = { tab = Tab.Settings },
                        label = { Text("Settings") },
                        icon = {}
                    )
                }
            }
        ) { padding ->
            when (tab) {
                Tab.Watchlist -> WatchlistScreen(modifier = Modifier.padding(padding), settings = settings)
                Tab.Alerts -> AlertsScreen(modifier = Modifier.padding(padding), settings = settings)
                Tab.Settings -> SettingsScreen(
                    modifier = Modifier.padding(padding),
                    settings = settings,
                    onSave = {
                        settings = it
                        saveSettings(context, it)
                    }
                )
            }
        }
    }
}
