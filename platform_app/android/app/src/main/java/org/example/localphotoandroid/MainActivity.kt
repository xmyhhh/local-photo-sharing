package org.example.localphotoandroid

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.example.localphotoandroid.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { startPhotoShareService() }
    private val mediaPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { results ->
        if (results.values.any { it }) {
            addSystemAlbums()
        } else {
            Toast.makeText(this, R.string.media_permission_needed, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        applySystemInsets()
        bindActions()
        refreshNetwork()
        refreshFolders()
        PhotoShareService.state.observe(this) { renderState(it) }
    }

    private fun applySystemInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val cutout = insets.getInsets(WindowInsetsCompat.Type.displayCutout())
            binding.header.updatePadding(
                left = 24.dp + maxOf(bars.left, cutout.left),
                top = 26.dp + maxOf(bars.top, cutout.top),
                right = 24.dp + maxOf(bars.right, cutout.right),
            )
            binding.content.updatePadding(
                left = 24.dp + maxOf(bars.left, cutout.left),
                right = 24.dp + maxOf(bars.right, cutout.right),
                bottom = 24.dp + maxOf(bars.bottom, cutout.bottom),
            )
            insets
        }
    }

    private fun bindActions() {
        binding.startStopButton.setOnClickListener {
            if (PhotoShareService.state.value?.running == true) {
                stopService(Intent(this, PhotoShareService::class.java))
                PhotoShareService.publish(ServiceState.stopped())
            } else {
                requestNotificationPermissionThenStart()
            }
        }
        binding.copyLanButton.setOnClickListener {
            val lanUrl = PhotoShareService.state.value?.lanUrl.orEmpty()
            if (lanUrl.isBlank()) return@setOnClickListener
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.lan_url), lanUrl))
            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
        }
        binding.openLocalButton.setOnClickListener {
            val localUrl = PhotoShareService.state.value?.localUrl.orEmpty()
            if (localUrl.isBlank()) return@setOnClickListener
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(localUrl)))
        }
        binding.refreshLogsButton.setOnClickListener {
            refreshLogs()
        }
        binding.clearLogsButton.setOnClickListener {
            serviceLogFile().writeText("")
            refreshLogs()
            Toast.makeText(this, R.string.logs_cleared, Toast.LENGTH_SHORT).show()
        }
        binding.copyLogsButton.setOnClickListener {
            val logs = binding.logText.text.toString()
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.logs_title), logs))
            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
        }
        binding.addSystemAlbumsButton.setOnClickListener {
            requestMediaPermissionThenAddSystemAlbums()
        }
        binding.addAppAlbumButton.setOnClickListener {
            addFolders(listOf(defaultAppPhotoDir()))
        }
        binding.scanExternalStorageButton.setOnClickListener {
            val candidates = externalStorageCandidates()
            if (candidates.isEmpty()) {
                Toast.makeText(this, R.string.no_external_storage, Toast.LENGTH_SHORT).show()
            } else {
                addFolders(candidates)
            }
        }
        binding.removeFoldersButton.setOnClickListener {
            showRemoveFoldersDialog()
        }
        binding.savePortButton.setOnClickListener {
            savePort()
        }
    }

    private fun requestNotificationPermissionThenStart() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            startPhotoShareService()
        }
    }

    private fun startPhotoShareService() {
        ContextCompat.startForegroundService(this, Intent(this, PhotoShareService::class.java))
    }

    private fun renderState(state: ServiceState) {
        binding.statusText.text = when {
            state.running -> getString(R.string.service_running)
            state.starting -> getString(R.string.service_starting)
            state.error != null -> getString(R.string.service_error)
            else -> getString(R.string.service_stopped)
        }
        binding.messageText.text = state.error ?: state.message ?: if (state.running) {
            getString(R.string.service_running_hint)
        } else {
            getString(R.string.service_ready_hint)
        }
        binding.localUrlText.text = state.localUrl.ifBlank { getString(R.string.url_placeholder) }
        binding.lanUrlText.text = state.lanUrl.ifBlank { getString(R.string.url_placeholder) }
        binding.startStopButton.text = if (state.running || state.starting) {
            getString(R.string.stop_service)
        } else {
            getString(R.string.start_service)
        }
        binding.copyLanButton.isEnabled = state.lanUrl.isNotBlank()
        binding.openLocalButton.isEnabled = state.localUrl.isNotBlank()
        refreshLogs()
    }

    private fun requestMediaPermissionThenAddSystemAlbums() {
        val permissions = when {
            Build.VERSION.SDK_INT >= 33 -> arrayOf(
                Manifest.permission.READ_MEDIA_IMAGES,
                Manifest.permission.READ_MEDIA_VIDEO,
            )
            else -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        val missing = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) {
            addSystemAlbums()
        } else {
            mediaPermissionLauncher.launch(missing.toTypedArray())
        }
    }

    private fun addSystemAlbums() {
        val roots = buildList {
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM)?.let { dcim ->
                add(File(dcim, "Camera"))
                add(dcim)
            }
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)?.let { add(it) }
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)?.let { add(it) }
            defaultAppPhotoDir().let { add(it) }
        }
        addFolders(roots)
    }

    private fun addFolders(candidates: List<File>) {
        val usable = candidates
            .map { it.absoluteFile }
            .onEach { it.mkdirs() }
            .filter { it.isDirectory && it.canRead() }
        if (usable.isEmpty()) return
        val config = readConfig()
        val existing = config.photoFolders.toMutableList()
        var changed = false
        usable.forEach { folder ->
            val path = folder.absolutePath
            if (existing.none { it == path }) {
                existing.add(path)
                changed = true
            }
        }
        if (!changed) {
            refreshFolders()
            return
        }
        val defaultSave = config.defaultSaveFolder.ifBlank { existing.first() }
        writeConfig(existing, defaultSave)
        refreshFolders()
        restartServiceIfRunning()
        Toast.makeText(this, R.string.folders_updated, Toast.LENGTH_SHORT).show()
    }

    private fun refreshFolders() {
        val folders = readConfig().photoFolders
        binding.foldersText.text = if (folders.isEmpty()) {
            getString(R.string.no_folders)
        } else {
            folders.mapIndexed { index, item -> "${index + 1}. $item" }.joinToString("\n")
        }
        binding.removeFoldersButton.isEnabled = folders.isNotEmpty()
    }

    private fun showRemoveFoldersDialog() {
        val config = readConfig()
        val folders = config.photoFolders
        if (folders.isEmpty()) return
        val checked = BooleanArray(folders.size)
        AlertDialog.Builder(this)
            .setTitle(R.string.remove_folders_title)
            .setMultiChoiceItems(folders.toTypedArray(), checked) { _, which, isChecked ->
                checked[which] = isChecked
            }
            .setNegativeButton(R.string.cancel, null)
            .setPositiveButton(R.string.confirm) { _, _ ->
                val remaining = folders.filterIndexed { index, _ -> !checked[index] }
                val safeRemaining = remaining.ifEmpty { listOf(defaultAppPhotoDir().absolutePath) }
                val defaultSave = config.defaultSaveFolder.takeIf { it in safeRemaining } ?: safeRemaining.first()
                writeConfig(safeRemaining, defaultSave)
                refreshFolders()
                restartServiceIfRunning()
                Toast.makeText(this, R.string.folders_updated, Toast.LENGTH_SHORT).show()
            }
            .show()
    }

    private fun refreshNetwork() {
        val config = readConfig()
        binding.portEditText.setText(config.port.toString())
        val localUrl = "http://127.0.0.1:${config.port}"
        binding.localUrlText.text = localUrl
    }

    private fun savePort() {
        val port = binding.portEditText.text?.toString()?.toIntOrNull()
        if (port == null || port !in 1..65535) {
            binding.portInputLayout.error = getString(R.string.invalid_port)
            return
        }
        binding.portInputLayout.error = null
        val config = readConfig()
        writeConfig(config.photoFolders, config.defaultSaveFolder, port)
        refreshNetwork()
        restartServiceIfRunning()
        Toast.makeText(this, R.string.port_updated, Toast.LENGTH_SHORT).show()
    }

    private fun restartServiceIfRunning() {
        if (PhotoShareService.state.value?.running == true || PhotoShareService.state.value?.starting == true) {
            stopService(Intent(this, PhotoShareService::class.java))
            PhotoShareService.publish(ServiceState.stopped())
            startPhotoShareService()
        }
    }

    private fun readConfig(): AndroidPhotoConfig {
        val file = configFile()
        val fallback = defaultAppPhotoDir().absolutePath
        if (!file.exists()) return AndroidPhotoConfig(listOf(fallback), fallback, 8000)
        return runCatching {
            val json = JSONObject(file.readText())
            val foldersJson = json.optJSONArray("photo_folders") ?: JSONArray()
            val folders = (0 until foldersJson.length())
                .mapNotNull { index -> foldersJson.optString(index).takeIf { it.isNotBlank() } }
            AndroidPhotoConfig(
                photoFolders = folders.ifEmpty { listOf(fallback) },
                defaultSaveFolder = json.optString("default_save_folder", fallback).ifBlank { fallback },
                port = json.optInt("port", 8000).coerceIn(1, 65535),
            )
        }.getOrElse {
            AndroidPhotoConfig(listOf(fallback), fallback, 8000)
        }
    }

    private fun writeConfig(photoFolders: List<String>, defaultSaveFolder: String, port: Int = readConfig().port) {
        val file = configFile()
        file.parentFile?.mkdirs()
        val json = if (file.exists()) {
            runCatching { JSONObject(file.readText()) }.getOrElse { JSONObject() }
        } else {
            JSONObject()
        }
        json.put("photo_folders", JSONArray(photoFolders))
        json.put("default_save_folder", defaultSaveFolder)
        json.put("host", "0.0.0.0")
        json.put("port", port)
        file.writeText(json.toString(2))
    }

    private fun externalStorageCandidates(): List<File> {
        val appExternal = getExternalFilesDirs(Environment.DIRECTORY_PICTURES)
            .drop(1)
            .filterNotNull()
            .filter { Environment.getExternalStorageState(it) == Environment.MEDIA_MOUNTED }
        val publicRoots = getExternalFilesDirs(null)
            .drop(1)
            .filterNotNull()
            .mapNotNull { appDir ->
                generateSequence(appDir) { it.parentFile }
                    .firstOrNull { it.name.equals("Android", ignoreCase = true) }
                    ?.parentFile
            }
            .flatMap { root ->
                listOf(File(root, "DCIM"), File(root, "Pictures"), File(root, "Download"))
            }
        return (appExternal + publicRoots).distinctBy { it.absolutePath }
    }

    private fun defaultAppPhotoDir(): File =
        getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: File(filesDir, "Pictures")

    private fun configFile(): File = File(File(filesDir, "photo_share"), "config.json")

    private fun refreshLogs() {
        val text = runCatching {
            val file = serviceLogFile()
            if (file.exists()) file.readText().takeLast(60000) else ""
        }.getOrElse { error ->
            error.stackTraceToString()
        }
        binding.logText.text = text.ifBlank { getString(R.string.logs_placeholder) }
    }

    private fun serviceLogFile(): File = File(File(filesDir, "photo_share"), "android_service.log")

    private val Int.dp: Int
        get() = (this * resources.displayMetrics.density).toInt()
}

private data class AndroidPhotoConfig(
    val photoFolders: List<String>,
    val defaultSaveFolder: String,
    val port: Int,
)
