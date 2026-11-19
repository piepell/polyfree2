# PolyFree Photogrammetry - Android Client Integration Guide

## Overview

This guide covers integrating the PhotoSphereGuide and PhotoSphereClient Android apps with the PolyFree FastAPI backend.

## Architecture

```
┌─────────────────┐     HTTPS      ┌──────────────────┐
│  Android App    │ ◄─────────────► │  FastAPI Backend │
│  (Client)       │   REST + WS    │  (PolyFree API)  │
└─────────────────┘                └──────────────────┘
                                            │
                                            ▼
                                   ┌──────────────────┐
                                   │  C++ Core Engine │
                                   │  (libpolyfree)   │
                                   └──────────────────┘
```

## Base Configuration

### Network Security Config

```xml
<!-- res/xml/network_security_config.xml -->
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.0.2.2</domain>  <!-- Android emulator -->
        <domain includeSubdomains="true">192.168.1.0/24</domain>  <!-- Local network -->
        <domain includeSubdomains="true">your-server.com</domain>  <!-- Production -->
    </domain-config>
</network-security-config>
```

```xml
<!-- AndroidManifest.xml -->
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ... >
```

### API Client Setup (Kotlin)

```kotlin
// PolyFreeApiClient.kt
class PolyFreeApiClient(
    private val baseUrl: String = "http://10.0.2.2:8000/api",
    private val apiKey: String? = null
) {
    private val client = OkHttpClient.Builder()
        .addInterceptor { chain ->
            val request = chain.request().newBuilder()
                .apply {
                    if (apiKey != null) {
                        addHeader("Authorization", "Bearer $apiKey")
                    }
                    addHeader("Content-Type", "application/json")
                }
                .build()
            chain.proceed(request)
        }
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .addCallAdapterFactory(CoroutineCallAdapterFactory())
        .build()

    val api: PolyFreeApi = retrofit.create(PolyFreeApi::class.java)
}

interface PolyFreeApi {
    @POST("auth/token")
    suspend fun getToken(@Body request: TokenRequest): TokenResponse

    @POST("jobs")
    suspend fun createJob(@Body request: JobCreate): JobResponse

    @Multipart
    @POST("jobs/{jobId}/upload")
    suspend fun uploadImages(
        @Path("jobId") jobId: String,
        @PartMap parts: Map<String, RequestBody>
    ): UploadResponse

    @POST("jobs/{jobId}/start")
    suspend fun startJob(@Path("jobId") jobId: String): StartResponse

    @GET("jobs/{jobId}/status")
    suspend fun getJobStatus(@Path("jobId") jobId: String): JobStatusResponse

    @GET("jobs/{jobId}/download/{format}")
    suspend fun downloadResult(
        @Path("jobId") jobId: String,
        @Path("format") format: String
    ): Response<ResponseBody>

    @GET("jobs/{jobId}/package")
    suspend fun downloadPackage(
        @Path("jobId") jobId: String,
        @Query("format") format: String = "zip"
    ): Response<ResponseBody>

    @GET("health")
    suspend fun healthCheck(): HealthResponse

    @GET("engine/status")
    suspend fun engineStatus(): EngineStatusResponse
}

data class TokenRequest(val username: String, val password: String)
data class TokenResponse(val access_token: String, val token_type: String, val expires_in: Int)
data class JobCreate(
    val quality: String = "high",
    val reconstruction_type: String = "mesh",
    val output_formats: List<String> = listOf("stl", "obj", "gltf"),
    val texture: Boolean = true,
    val max_faces: Int? = 500000,
    val scale: Float? = null
)
data class JobResponse(val job_id: String, val status: String, val message: String, val progress: Float)
data class UploadResponse(val upload_id: String, val upload_url: String, val expires_in: Int)
data class StartResponse(val message: String, val job_id: String)
```

## PhotoSphereGuide Integration (Capture App)

### Capture Flow

```kotlin
// CaptureViewModel.kt
@HiltViewModel
class CaptureViewModel @Inject constructor(
    private val apiClient: PolyFreeApiClient,
    private val cameraManager: CameraManager,
    private val orientationManager: OrientationManager
) : ViewModel() {

    private var currentJobId: String? = null
    private val capturedImages = mutableListOf<File>()

    // 20 positions for spherical capture
    private val capturePositions = listOf(
        Position(0f, 0f),      // Front center
        Position(45f, 0f),     // Front right
        Position(90f, 0f),     // Right
        Position(135f, 0f),    // Back right
        Position(180f, 0f),    // Back
        Position(-135f, 0f),   // Back left
        Position(-90f, 0f),    // Left
        Position(-45f, 0f),    // Front left
        Position(0f, 30f),     // Up center
        Position(45f, 30f),    // Up right
        Position(90f, 30f),    // Up right side
        Position(135f, 30f),   // Up back right
        Position(180f, 30f),   // Up back
        Position(-135f, 30f),  // Up back left
        Position(-90f, 30f),   // Up left side
        Position(-45f, 30f),   // Up front left
        Position(0f, -30f),    // Down center
        Position(45f, -30f),   // Down right
        Position(90f, -30f),   // Down right side
        Position(135f, -30f)   // Down back right
    )

    fun startNewSession() = viewModelScope.launch {
        try {
            val job = apiClient.api.createJob(JobCreate(
                quality = "high",
                reconstruction_type = "mesh",
                output_formats = listOf("stl", "obj", "gltf"),
                texture = true
            ))
            currentJobId = job.job_id
            capturedImages.clear()
            _captureState.value = CaptureState.Ready(positionIndex = 0)
        } catch (e: Exception) {
            _error.value = "Failed to create job: ${e.message}"
        }
    }

    fun captureCurrentPosition() = viewModelScope.launch {
        val position = capturePositions[currentPositionIndex]
        
        // Wait for device to reach target orientation
        orientationManager.waitForOrientation(position.yaw, position.pitch)
        
        // Capture photo
        val imageFile = cameraManager.capturePhoto()
        capturedImages.add(imageFile)
        
        // Update UI
        _captureState.value = CaptureState.Captured(
            positionIndex = currentPositionIndex,
            imagePreview = imageFile
        )
    }

    fun nextPosition() {
        if (currentPositionIndex < capturePositions.size - 1) {
            _captureState.value = CaptureState.Ready(positionIndex = currentPositionIndex + 1)
        } else {
            // All positions captured - ready to upload
            _captureState.value = CaptureState.ReadyToUpload(totalImages = capturedImages.size)
        }
    }

    fun uploadAndProcess() = viewModelScope.launch {
        _captureState.value = CaptureState.Uploading(progress = 0f)
        
        try {
            // Upload all images
            val parts = capturedImages.mapIndexed { index, file ->
                val requestBody = file.asRequestBody("image/jpeg".toMediaType())
                val part = MultipartBody.Part.createFormData("files", "img_$index.jpg", requestBody)
                "file$index" to part
            }.toMap()
            
            apiClient.api.uploadImages(currentJobId!!, parts)
            
            // Start processing
            apiClient.api.startJob(currentJobId!!)
            
            // Poll for completion
            pollForCompletion()
            
        } catch (e: Exception) {
            _error.value = "Upload failed: ${e.message}"
        }
    }

    private fun pollForCompletion() = viewModelScope.launch {
        while (true) {
            delay(5000)
            val status = apiClient.api.getJobStatus(currentJobId!!)
            
            _captureState.value = CaptureState.Processing(
                progress = status.progress,
                currentStep = status.current_step ?: "processing",
                message = status.message
            )
            
            when (status.status) {
                "completed" -> {
                    downloadResults()
                    break
                }
                "failed" -> {
                    _error.value = "Processing failed: ${status.error}"
                    break
                }
                else -> continue
            }
        }
    }

    private fun downloadResults() = viewModelScope.launch {
        _captureState.value = CaptureState.Downloading(progress = 0f)
        
        try {
            val formats = listOf("stl", "obj", "gltf")
            val downloadedFiles = mutableMapOf<String, File>()
            
            for ((index, format) in formats.withIndex()) {
                val response = apiClient.api.downloadResult(currentJobId!!, format)
                val file = saveResultFile(response.body()!!, "model_${currentJobId}.$format")
                downloadedFiles[format] = file
                
                _captureState.value = CaptureState.Downloading(
                    progress = (index + 1).toFloat() / formats.size
                )
            }
            
            _captureState.value = CaptureState.Completed(downloadedFiles)
            
        } catch (e: Exception) {
            _error.value = "Download failed: ${e.message}"
        }
    }
}

sealed class CaptureState {
    data class Ready(val positionIndex: Int) : CaptureState()
    data class Captured(val positionIndex: Int, val imagePreview: File) : CaptureState()
    data class ReadyToUpload(val totalImages: Int) : CaptureState()
    data class Uploading(val progress: Float) : CaptureState()
    data class Processing(
        val progress: Float,
        val currentStep: String,
        val message: String
    ) : CaptureState()
    data class Downloading(val progress: Float) : CaptureState()
    data class Completed(val files: Map<String, File>) : CaptureState()
}
```

### Camera Overlay (Sphere Guide)

```kotlin
// SphereOverlayView.kt
class SphereOverlayView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val targetPaint = Paint().apply {
        color = Color.GREEN
        style = Paint.Style.STROKE
        strokeWidth = 4f
    }
    private val currentPaint = Paint().apply {
        color = Color.RED
        style = Paint.Style.STROKE
        strokeWidth = 4f
    }
    private val guidePaint = Paint().apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 2f
        alpha = 128
    }

    var targetYaw: Float = 0f
    var targetPitch: Float = 0f
    var currentYaw: Float = 0f
    var currentPitch: Float = 0f
    var isAligned: Boolean = false

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        
        val centerX = width / 2f
        val centerY = height / 2f
        val radius = min(width, height) * 0.35f

        // Draw sphere wireframe
        drawSphereWireframe(canvas, centerX, centerY, radius)
        
        // Draw target position
        val targetPoint = sphericalToScreen(targetYaw, targetPitch, centerX, centerY, radius)
        canvas.drawCircle(targetPoint.x, targetPoint.y, 20f, targetPaint)
        
        // Draw current position
        val currentPoint = sphericalToScreen(currentYaw, currentPitch, centerX, centerY, radius)
        canvas.drawCircle(currentPoint.x, currentPoint.y, 20f, if (isAligned) targetPaint else currentPaint)
        
        // Draw alignment indicator
        if (isAligned) {
            drawAlignmentIndicator(canvas, centerX, centerY)
        }
    }

    private fun drawSphereWireframe(canvas: Canvas, cx: Float, cy: Float, r: Float) {
        // Latitude lines
        for (lat in -80..80 step 20) {
            val points = mutableListOf<PointF>()
            for (lon in -180..180 step 10) {
                points.add(sphericalToScreen(lon.toFloat(), lat.toFloat(), cx, cy, r))
            }
            drawPath(canvas, points)
        }
        
        // Longitude lines
        for (lon in -180..180 step 30) {
            val points = mutableListOf<PointF>()
            for (lat in -90..90 step 10) {
                points.add(sphericalToScreen(lon.toFloat(), lat.toFloat(), cx, cy, r))
            }
            drawPath(canvas, points)
        }
    }

    private fun sphericalToScreen(yaw: Float, pitch: Float, cx: Float, cy: Float, r: Float): PointF {
        val yawRad = Math.toRadians(yaw.toDouble())
        val pitchRad = Math.toRadians(pitch.toDouble())
        
        val x = cx + r * Math.cos(pitchRad) * Math.sin(yawRad)
        val y = cy - r * Math.sin(pitchRad)  // Invert Y for screen coordinates
        
        return PointF(x.toFloat(), y.toFloat())
    }

    private fun drawPath(canvas: Canvas, points: List<PointF>) {
        val path = Path()
        points.forEachIndexed { index, point ->
            if (index == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
        }
        canvas.drawPath(path, guidePaint)
    }
}
```

## PhotoSphereClient Integration (Processing App)

### Job Management UI

```kotlin
// JobListViewModel.kt
@HiltViewModel
class JobListViewModel @Inject constructor(
    private val apiClient: PolyFreeApiClient,
    private val localDatabase: AppDatabase
) : ViewModel() {

    private val _jobs = MutableStateFlow<List<JobSummary>>(emptyList())
    val jobs: StateFlow<List<JobSummary>> = _jobs

    fun loadJobs() = viewModelScope.launch {
        try {
            val remoteJobs = apiClient.api.listJobs()
            val localJobs = localDatabase.jobDao().getAllJobs()
            
            // Merge and deduplicate
            val allJobs = (remoteJobs + localJobs).distinctBy { it.job_id }
                .sortedByDescending { it.created_at }
            
            _jobs.value = allJobs
        } catch (e: Exception) {
            // Fallback to local only
            _jobs.value = localDatabase.jobDao().getAllJobs()
        }
    }

    fun createLocalJob(job: JobCreate) = viewModelScope.launch {
        val jobId = UUID.randomUUID().toString().substring(0, 8)
        val jobEntity = JobEntity(
            job_id = jobId,
            status = "pending",
            quality = job.quality,
            reconstruction_type = job.reconstruction_type,
            output_formats = job.output_formats.joinToString(","),
            texture = job.texture,
            max_faces = job.max_faces ?: 500000,
            scale = job.scale,
            created_at = System.currentTimeMillis()
        )
        localDatabase.jobDao().insert(jobEntity)
        loadJobs()
    }

    fun deleteJob(jobId: String) = viewModelScope.launch {
        try {
            apiClient.api.deleteJob(jobId)
        } catch (e: Exception) {
            // Ignore remote errors
        }
        localDatabase.jobDao().delete(jobId)
        loadJobs()
    }
}
```

### Result Viewer

```kotlin
// ModelViewerActivity.kt
class ModelViewerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityModelViewerBinding
    private var modelFile: File? = null
    private var modelFormat: String = "gltf"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityModelViewerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        modelFile = intent.getParcelableExtra("model_file")
        modelFormat = intent.getStringExtra("model_format") ?: "gltf"

        setupViewer()
        setupDownloadButtons()
    }

    private fun setupViewer() {
        when (modelFormat) {
            "gltf", "glb" -> loadGLTF(modelFile!!)
            "obj" -> loadOBJ(modelFile!!)
            "stl" -> loadSTL(modelFile!!)
        }
    }

    private fun loadGLTF(file: File) {
        // Use Filament or Sceneform for GLTF rendering
        val engine = Engine.create()
        val scene = engine.createScene()
        val renderer = engine.createRenderer()
        
        val loader = GltfioLoader(engine)
        loader.loadResources(
            Uri.fromFile(file),
            { finish ->
                val renderable = finish.getRenderable(0)
                // Add to scene
            },
            { error ->
                Log.e("ModelViewer", "Failed to load GLTF", error)
            }
        )
    }

    private fun setupDownloadButtons() {
        binding.btnDownloadStl.setOnClickListener { downloadFormat("stl") }
        binding.btnDownloadObj.setOnClickListener { downloadFormat("obj") }
        binding.btnDownloadGltf.setOnClickListener { downloadFormat("gltf") }
        binding.btnDownloadPly.setOnClickListener { downloadFormat("ply") }
    }

    private fun downloadFormat(format: String) {
        // Trigger re-download in requested format
        val jobId = intent.getStringExtra("job_id") ?: return
        
        lifecycleScope.launch {
            try {
                val response = apiClient.api.downloadResult(jobId, format)
                val file = saveToDownloads(response.body()!!, "model_$jobId.$format")
                showToast("Saved to Downloads: $file")
            } catch (e: Exception) {
                showToast("Download failed: ${e.message}")
            }
        }
    }
}
```

## WebSocket Progress Updates (Real-time)

```kotlin
// ProgressWebSocket.kt
class ProgressWebSocket(private val jobId: String) {
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient()
    private val progressCallback: (Float, String, String) -> Unit

    init {
        val request = Request.Builder()
            .url("ws://10.0.2.2:8000/api/jobs/$jobId/ws")
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    val progress = json.getDouble("progress").toFloat()
                    val step = json.getString("step")
                    val message = json.getString("message")
                    progressCallback(progress, step, message)
                } catch (e: Exception) {
                    Log.e("ProgressWS", "Parse error", e)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("ProgressWS", "Connection failed", t)
            }
        })
    }

    fun close() {
        webSocket?.cancel()
    }
}
```

## Error Handling & Retry Logic

```kotlin
// ApiErrorHandler.kt
class ApiErrorHandler {
    companion object {
        @OptIn(ExperimentalCoroutinesApi::class)
        suspend fun <T> withRetry(
            retries: Int = 3,
            delayMs: Long = 1000,
            block: suspend () -> T
        ): Result<T> {
            var attempt = 0
            while (true) {
                try {
                    return Result.success(block())
                } catch (e: Exception) {
                    attempt++
                    if (attempt >= retries) {
                        return Result.failure(e)
                    }
                    delay(delayMs * attempt) // Exponential backoff
                }
            }
        }

        fun handleError(e: Exception): String {
            return when (e) {
                is IOException -> "Network error. Check connection."
                is HttpException -> when (e.response?.code()) {
                    401 -> "Session expired. Please login again."
                    404 -> "Resource not found."
                    500 -> "Server error. Try again later."
                    else -> "Request failed: ${e.response?.code()}"
                }
                is SocketTimeoutException -> "Request timeout. Try again."
                else -> "Unexpected error: ${e.message}"
            }
        }
    }
}
```

## Testing Checklist

### Local Development

- [ ] Start backend: `cd PhotogrammetryBackend && python -m uvicorn app.main:app --reload`
- [ ] Test health: `curl http://10.0.2.2:8000/api/health`
- [ ] Create job via app
- [ ] Capture 20 photos using sphere overlay
- [ ] Upload and process
- [ ] Verify results download (STL, OBJ, GLTF)
- [ ] Test on real device with USB debugging

### Production Deployment

- [ ] Update `baseUrl` to production server
- [ ] Configure HTTPS/TLS certificates
- [ ] Set up API key authentication
- [ ] Test with real photogrammetry datasets
- [ ] Verify GPU acceleration on server
- [ ] Load test with concurrent jobs

---

**PolyFree Android Integration v1.0.0**  
Compatible with PhotoSphereGuide & PhotoSphereClient