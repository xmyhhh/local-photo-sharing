package org.example.localphotoandroid

import android.Manifest
import android.content.ContentUris
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.ImageView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.example.localphotoandroid.databinding.ActivityMainBinding
import org.example.localphotoandroid.databinding.ItemPhotoBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val adapter = PhotoAdapter()
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        refreshPhotos()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.photoGrid.layoutManager = GridLayoutManager(this, 3)
        binding.photoGrid.adapter = adapter
        binding.permissionButton.setOnClickListener { requestPhotoPermissions() }
        binding.refreshButton.setOnClickListener { refreshPhotos() }
        refreshPhotos()
    }

    private fun refreshPhotos() {
        if (!hasPhotoPermission()) {
            adapter.submitList(emptyList())
            binding.permissionButton.isEnabled = true
            binding.statusText.text = "需要照片权限才能读取本地图库"
            return
        }
        binding.permissionButton.isEnabled = false
        val photos = loadLocalPhotos()
        adapter.submitList(photos)
        binding.statusText.text = if (photos.isEmpty()) {
            getString(R.string.empty_gallery)
        } else {
            "已加载 ${photos.size} 张本地照片"
        }
    }

    private fun hasPhotoPermission(): Boolean {
        val permissions = requiredPermissions()
        return permissions.any {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestPhotoPermissions() {
        permissionLauncher.launch(requiredPermissions())
    }

    private fun requiredPermissions(): Array<String> {
        return when {
            Build.VERSION.SDK_INT >= 34 -> arrayOf(
                Manifest.permission.READ_MEDIA_IMAGES,
                Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED,
            )
            Build.VERSION.SDK_INT >= 33 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES)
            else -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
    }

    private fun loadLocalPhotos(): List<PhotoItem> {
        val collection = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        val projection = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.DATE_ADDED,
        )
        val sortOrder = "${MediaStore.Images.Media.DATE_ADDED} DESC"
        val result = mutableListOf<PhotoItem>()
        contentResolver.query(collection, projection, null, null, sortOrder)?.use { cursor ->
            val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val nameColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
            while (cursor.moveToNext()) {
                val id = cursor.getLong(idColumn)
                val name = cursor.getString(nameColumn) ?: ""
                val uri = ContentUris.withAppendedId(collection, id)
                result += PhotoItem(id = id, name = name, uri = uri)
            }
        }
        return result
    }
}

data class PhotoItem(
    val id: Long,
    val name: String,
    val uri: Uri,
)

class PhotoAdapter : RecyclerView.Adapter<PhotoViewHolder>() {
    private val items = mutableListOf<PhotoItem>()

    fun submitList(nextItems: List<PhotoItem>) {
        items.clear()
        items.addAll(nextItems)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): PhotoViewHolder {
        val binding = ItemPhotoBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        val size = parent.resources.displayMetrics.widthPixels / 3
        binding.root.layoutParams = RecyclerView.LayoutParams(size, size)
        return PhotoViewHolder(binding)
    }

    override fun onBindViewHolder(holder: PhotoViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size
}

class PhotoViewHolder(
    private val binding: ItemPhotoBinding,
) : RecyclerView.ViewHolder(binding.root) {
    fun bind(item: PhotoItem) {
        binding.photoImage.scaleType = ImageView.ScaleType.CENTER_CROP
        binding.photoImage.setImageURI(item.uri)
    }
}
