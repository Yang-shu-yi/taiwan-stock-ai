package com.taiwanstock.client

import android.content.Context

data class AppSettings(
    val baseUrl: String,
    val apiKey: String,
)

private const val PREFS_NAME = "taiwan_stock_client"
private const val KEY_BASE_URL = "base_url"
private const val KEY_API_KEY = "api_key"

fun loadSettings(context: Context): AppSettings {
    val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    return AppSettings(
        baseUrl = prefs.getString(KEY_BASE_URL, "http://192.168.1.2:8000") ?: "",
        apiKey = prefs.getString(KEY_API_KEY, "") ?: "",
    )
}

fun saveSettings(context: Context, settings: AppSettings) {
    val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    prefs.edit()
        .putString(KEY_BASE_URL, settings.baseUrl.trim().trimEnd('/'))
        .putString(KEY_API_KEY, settings.apiKey.trim())
        .apply()
}
