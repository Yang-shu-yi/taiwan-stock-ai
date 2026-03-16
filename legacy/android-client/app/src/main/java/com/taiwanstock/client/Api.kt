package com.taiwanstock.client

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

data class AlertItem(
    val ts: Long,
    val code: String,
    val status: String,
    val message: String,
)

object Api {
    private val client = OkHttpClient()
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    private fun auth(req: Request.Builder, apiKey: String): Request.Builder {
        return req.header("X-API-Key", apiKey)
    }

    suspend fun health(baseUrl: String): Boolean = withContext(Dispatchers.IO) {
        val req = Request.Builder().url("$baseUrl/health").get().build()
        client.newCall(req).execute().use { it.isSuccessful }
    }

    suspend fun getWatchlist(baseUrl: String, apiKey: String): List<String> = withContext(Dispatchers.IO) {
        val req = auth(Request.Builder().url("$baseUrl/watchlist").get(), apiKey).build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) return@withContext emptyList()
            val body = res.body?.string() ?: return@withContext emptyList()
            val obj = JSONObject(body)
            val arr = obj.optJSONArray("codes") ?: JSONArray()
            (0 until arr.length()).mapNotNull { i -> arr.optString(i).takeIf { it.isNotBlank() } }
        }
    }

    suspend fun addCodes(baseUrl: String, apiKey: String, codes: List<String>): List<String> = withContext(Dispatchers.IO) {
        val payload = JSONObject().put("codes", JSONArray(codes))
        val req = auth(
            Request.Builder()
                .url("$baseUrl/watchlist/add")
                .post(payload.toString().toRequestBody(jsonMedia)),
            apiKey
        ).build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) return@withContext emptyList()
            val body = res.body?.string() ?: return@withContext emptyList()
            val obj = JSONObject(body)
            val arr = obj.optJSONArray("codes") ?: JSONArray()
            (0 until arr.length()).mapNotNull { i -> arr.optString(i).takeIf { it.isNotBlank() } }
        }
    }

    suspend fun delCodes(baseUrl: String, apiKey: String, codes: List<String>): List<String> = withContext(Dispatchers.IO) {
        val payload = JSONObject().put("codes", JSONArray(codes))
        val req = auth(
            Request.Builder()
                .url("$baseUrl/watchlist/del")
                .post(payload.toString().toRequestBody(jsonMedia)),
            apiKey
        ).build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) return@withContext emptyList()
            val body = res.body?.string() ?: return@withContext emptyList()
            val obj = JSONObject(body)
            val arr = obj.optJSONArray("codes") ?: JSONArray()
            (0 until arr.length()).mapNotNull { i -> arr.optString(i).takeIf { it.isNotBlank() } }
        }
    }

    suspend fun getAlerts(baseUrl: String, apiKey: String, limit: Int = 100): List<AlertItem> = withContext(Dispatchers.IO) {
        val req = auth(Request.Builder().url("$baseUrl/alerts?limit=$limit").get(), apiKey).build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) return@withContext emptyList()
            val body = res.body?.string() ?: return@withContext emptyList()
            val obj = JSONObject(body)
            val arr = obj.optJSONArray("alerts") ?: JSONArray()
            (0 until arr.length()).mapNotNull { i ->
                val a = arr.optJSONObject(i) ?: return@mapNotNull null
                AlertItem(
                    ts = a.optLong("ts", 0L),
                    code = a.optString("code", ""),
                    status = a.optString("status", ""),
                    message = a.optString("message", ""),
                )
            }
        }
    }
}
