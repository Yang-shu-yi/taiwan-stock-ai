package com.taiwanstock.client

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(modifier: Modifier = Modifier, settings: AppSettings, onSave: (AppSettings) -> Unit) {
    var baseUrl by remember { mutableStateOf(TextFieldValue(settings.baseUrl)) }
    var apiKey by remember { mutableStateOf(TextFieldValue(settings.apiKey)) }

    Column(modifier = modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Backend Settings", style = MaterialTheme.typography.titleLarge)
        OutlinedTextField(value = baseUrl, onValueChange = { baseUrl = it }, label = { Text("Base URL") })
        OutlinedTextField(value = apiKey, onValueChange = { apiKey = it }, label = { Text("API Key") })
        Button(onClick = { onSave(AppSettings(baseUrl.text, apiKey.text)) }) {
            Text("Save")
        }
        Text("Tip: Use http://<pi-ip>:8000 (LAN)")
    }
}


@Composable
fun WatchlistScreen(modifier: Modifier = Modifier, settings: AppSettings) {
    val scope = rememberCoroutineScope()

    var loading by remember { mutableStateOf(false) }
    var codes by remember { mutableStateOf(listOf<String>()) }
    var input by remember { mutableStateOf(TextFieldValue("")) }
    var error by remember { mutableStateOf<String?>(null) }

    fun refresh() {
        scope.launch {
            loading = true
            error = null
            try {
                codes = Api.getWatchlist(settings.baseUrl, settings.apiKey)
            } catch (e: Exception) {
                error = e.message ?: "request failed"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(settings.baseUrl, settings.apiKey) { refresh() }

    Column(modifier = modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Watchlist", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Button(onClick = { refresh() }, enabled = !loading) { Text("Refresh") }
        }

        if (error != null) {
            Text("Error: $error", color = MaterialTheme.colorScheme.error)
        }

        OutlinedTextField(
            value = input,
            onValueChange = { input = it },
            label = { Text("Add codes (comma-separated)") },
            modifier = Modifier.fillMaxWidth(),
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = {
                    val toAdd = input.text.split(",").map { it.trim() }.filter { it.isNotBlank() }
                    scope.launch {
                        loading = true
                        error = null
                        try {
                            codes = Api.addCodes(settings.baseUrl, settings.apiKey, toAdd)
                            input = TextFieldValue("")
                        } catch (e: Exception) {
                            error = e.message ?: "request failed"
                        } finally {
                            loading = false
                        }
                    }
                },
                enabled = !loading
            ) { Text("Add") }

            Button(
                onClick = {
                    val toDel = input.text.split(",").map { it.trim() }.filter { it.isNotBlank() }
                    scope.launch {
                        loading = true
                        error = null
                        try {
                            codes = Api.delCodes(settings.baseUrl, settings.apiKey, toDel)
                            input = TextFieldValue("")
                        } catch (e: Exception) {
                            error = e.message ?: "request failed"
                        } finally {
                            loading = false
                        }
                    }
                },
                enabled = !loading
            ) { Text("Delete") }
        }

        Divider()

        if (loading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(codes) { c ->
                Text(c)
            }
        }
    }
}


@Composable
fun AlertsScreen(modifier: Modifier = Modifier, settings: AppSettings) {
    val scope = rememberCoroutineScope()

    var loading by remember { mutableStateOf(false) }
    var alerts by remember { mutableStateOf(listOf<AlertItem>()) }
    var error by remember { mutableStateOf<String?>(null) }

    fun refresh() {
        scope.launch {
            loading = true
            error = null
            try {
                alerts = Api.getAlerts(settings.baseUrl, settings.apiKey, limit = 200).reversed()
            } catch (e: Exception) {
                error = e.message ?: "request failed"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(settings.baseUrl, settings.apiKey) { refresh() }

    Column(modifier = modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Alerts", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Button(onClick = { refresh() }, enabled = !loading) { Text("Refresh") }
        }

        if (error != null) {
            Text("Error: $error", color = MaterialTheme.colorScheme.error)
        }

        if (loading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(alerts) { a ->
                ElevatedCard {
                    Column(modifier = Modifier.fillMaxWidth().padding(12.dp)) {
                        Text("${a.code} ${a.status}")
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(a.message)
                    }
                }
            }
        }
    }
}
