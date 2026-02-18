using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight.Server;
using Jellyfin.Plugin.Ambilight.Services;
using Jellyfin.Plugin.Ambilight.Tasks;
using MediaBrowser.Controller.Library;
using MediaBrowser.Model.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;

namespace Jellyfin.Plugin.Ambilight.Api;

/// <summary>
/// Ambilight API controller for configuration and control.
/// </summary>
[ApiController]
[Route("Ambilight")]
public class AmbilightController : ControllerBase
{
    private ILibraryManager? GetLibraryManager()
    {
        try
        {
            return HttpContext.RequestServices.GetService<ILibraryManager>();
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Gets the current plugin configuration.
    /// </summary>
    /// <returns>The plugin configuration.</returns>
    [HttpGet("Configuration")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public ActionResult<PluginConfiguration> GetConfiguration()
    {
        var config = Plugin.Instance?.Configuration;
        if (config == null)
        {
            return NotFound();
        }
        
        return Ok(config);
    }

    /// <summary>
    /// Updates the plugin configuration.
    /// </summary>
    /// <param name="configuration">The new configuration.</param>
    /// <returns>No content.</returns>
    [HttpPost("Configuration")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public ActionResult UpdateConfiguration([FromBody, Required] PluginConfiguration configuration)
    {
        if (Plugin.Instance == null)
        {
            return NotFound();
        }

        Plugin.Instance.UpdateConfiguration(configuration);
        Plugin.Instance.SaveConfiguration();
        
        return NoContent();
    }

    /// <summary>
    /// Gets ambilight extraction status for multiple items in a single batch request.
    /// </summary>
    /// <param name="itemIds">Array of item IDs (GUIDs).</param>
    /// <returns>Dictionary mapping item IDs to their extraction status.</returns>
    [HttpPost("Status/Batch")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public ActionResult<Dictionary<string, AmbilightStatusResponse>> GetBatchStatus([FromBody] string[] itemIds)
    {
        try
        {
            var libraryManager = GetLibraryManager();
            if (libraryManager == null)
            {
                return BadRequest(new { error = "LibraryManager not available" });
            }

            var config = Plugin.Instance?.Configuration;
            var dataFolder = string.IsNullOrWhiteSpace(config?.AmbilightDataFolder) ? "/data/ambilight" : config!.AmbilightDataFolder.Trim();
            var entryPoint = AmbilightEntryPoint.Instance;
            var results = new Dictionary<string, AmbilightStatusResponse>();

            foreach (var itemId in itemIds)
            {
                if (string.IsNullOrWhiteSpace(itemId) || !Guid.TryParse(itemId, out var guid))
                {
                    continue; // Skip invalid IDs
                }

                var item = libraryManager.GetItemById(guid);
                if (item == null)
                {
                    continue; // Skip items that don't exist
                }

                var binPath = Path.Combine(dataFolder, guid.ToString("N") + ".bin");
                string? extractionStatus = null;
                int extractionProgress = 0;
                ulong extractionFramesCurrent = 0;
                ulong extractionFramesTotal = 0;

                if (entryPoint?.Storage != null)
                {
                    var ambiItem = entryPoint.Storage.GetItem(guid.ToString("N"));
                    if (ambiItem != null)
                    {
                        extractionStatus = ambiItem.ExtractionStatus;
                        extractionProgress = ambiItem.ExtractionProgress;
                        extractionFramesCurrent = ambiItem.ExtractionFramesCurrent;
                        extractionFramesTotal = ambiItem.ExtractionFramesTotal;
                    }
                }

                results[itemId] = new AmbilightStatusResponse
                {
                    ItemId = guid,
                    ItemName = item.Name,
                    HasBinary = System.IO.File.Exists(binPath),
                    BinaryPath = binPath,
                    BinarySize = System.IO.File.Exists(binPath) ? new FileInfo(binPath).Length : 0,
                    ExtractionStatus = extractionStatus,
                    ExtractionProgress = extractionProgress,
                    ExtractionFramesCurrent = extractionFramesCurrent,
                    ExtractionFramesTotal = extractionFramesTotal
                };
            }

            return Ok(results);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { 
                error = ex.Message, 
                type = ex.GetType().Name
            });
        }
    }

    /// <summary>
    /// Gets ambilight extraction status for a specific item.
    /// </summary>
    /// <param name="itemId">The item ID (GUID, with or without dashes).</param>
    /// <returns>Extraction status.</returns>
    [HttpGet("Status/{itemId}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public ActionResult<AmbilightStatusResponse> GetStatus([FromRoute, Required] string itemId)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(itemId) || !Guid.TryParse(itemId, out var guid))
            {
                return BadRequest(new { error = "Invalid item ID", itemId });
            }

            var libraryManager = GetLibraryManager();
            if (libraryManager == null)
            {
                return StatusCode(500, new { error = "LibraryManager not available" });
            }

            var item = libraryManager.GetItemById(guid);
            if (item == null)
            {
                return Ok(new AmbilightStatusResponse
                {
                    ItemId = guid,
                    ItemName = null,
                    HasBinary = false,
                    BinaryPath = null,
                    BinarySize = 0
                });
            }

            if (string.IsNullOrEmpty(item.Path))
            {
                return Ok(new AmbilightStatusResponse
                {
                    ItemId = guid,
                    ItemName = item.Name,
                    HasBinary = false,
                    BinaryPath = null,
                    BinarySize = 0
                });
            }

            var config = Plugin.Instance?.Configuration;
            var dataFolder = string.IsNullOrWhiteSpace(config?.AmbilightDataFolder) ? "/data/ambilight" : config!.AmbilightDataFolder.Trim();
            var binPath = Path.Combine(dataFolder, guid.ToString("N") + ".bin");

            // Try to get extraction progress from storage
            var entryPoint = AmbilightEntryPoint.Instance;
            string? extractionStatus = null;
            int extractionProgress = 0;
            ulong extractionFramesCurrent = 0;
            ulong extractionFramesTotal = 0;
            
            if (entryPoint?.Storage != null)
            {
                var ambiItem = entryPoint.Storage.GetItem(guid.ToString("N"));
                if (ambiItem != null)
                {
                    extractionStatus = ambiItem.ExtractionStatus;
                    extractionProgress = ambiItem.ExtractionProgress;
                    extractionFramesCurrent = ambiItem.ExtractionFramesCurrent;
                    extractionFramesTotal = ambiItem.ExtractionFramesTotal;
                    
                    // Debug logging
                    if (extractionStatus == "extracting")
                    {
                        System.Diagnostics.Debug.WriteLine($"[Ambilight] API Status: Item {item.Name} is extracting at {extractionProgress}% ({extractionFramesCurrent}/{extractionFramesTotal})");
                    }
                }
                else
                {
                    System.Diagnostics.Debug.WriteLine($"[Ambilight] API Status: No storage item found for {guid:N}");
                }
            }
            else
            {
                System.Diagnostics.Debug.WriteLine("[Ambilight] API Status: Storage not available");
            }

            var status = new AmbilightStatusResponse
            {
                ItemId = guid,
                ItemName = item.Name,
                HasBinary = System.IO.File.Exists(binPath),
                BinaryPath = binPath,
                BinarySize = System.IO.File.Exists(binPath) ? new FileInfo(binPath).Length : 0,
                ExtractionStatus = extractionStatus,
                ExtractionProgress = extractionProgress,
                ExtractionFramesCurrent = extractionFramesCurrent,
                ExtractionFramesTotal = extractionFramesTotal
            };

            return Ok(status);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { 
                error = ex.Message, 
                type = ex.GetType().Name,
                stackTrace = ex.StackTrace 
            });
        }
    }

    /// <summary>
    /// Triggers the scheduled task to extract all pending items.
    /// </summary>
    /// <returns>Result with task status.</returns>
    [HttpPost("ExtractAllPending")]
    [ProducesResponseType(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public ActionResult<AmbilightExtractAllResponse> ExtractAllPending()
    {
        try
        {
            var taskManager = HttpContext.RequestServices.GetService<ITaskManager>();
            if (taskManager == null)
            {
                return StatusCode(500, new { error = "Task manager not available" });
            }

            // Find the extraction task
            var extractionTask = taskManager.ScheduledTasks
                .FirstOrDefault(t => t.ScheduledTask is ExtractPendingAmbilightTask);
            
            if (extractionTask == null)
            {
                return StatusCode(500, new { error = "Extraction task not found. Restart Jellyfin to register the task." });
            }
            
            // Check if task is already running
            if (extractionTask.State == TaskState.Running)
            {
                return Ok(new AmbilightExtractAllResponse
                {
                    QueuedCount = 0,
                    Message = "Extraction task is already running. Check Jellyfin Dashboard > Scheduled Tasks for progress."
                });
            }

            // Trigger the task using the task manager
            taskManager.Execute(extractionTask, new MediaBrowser.Model.Tasks.TaskOptions());

            return Accepted(new AmbilightExtractAllResponse
            {
                QueuedCount = -1, // Unknown at this point, task will count during execution
                Message = "Extraction task started. Check Jellyfin Dashboard > Scheduled Tasks for progress."
            });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { 
                error = ex.Message,
                type = ex.GetType().Name,
                stackTrace = ex.StackTrace 
            });
        }
    }

    /// <summary>
    /// Triggers ambilight extraction for a specific item.
    /// </summary>
    /// <param name="itemId">The item ID.</param>
    /// <returns>Extraction result.</returns>
    [HttpPost("Extract/{itemId}")]
    [ProducesResponseType(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public ActionResult<AmbilightExtractResponse> ExtractItem([FromRoute, Required] string itemId)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(itemId) || !Guid.TryParse(itemId, out var guid))
            {
                return BadRequest(new { error = "Invalid item ID", itemId });
            }

            var libraryManager = GetLibraryManager();
            if (libraryManager == null)
            {
                return StatusCode(500, new { error = "LibraryManager not available" });
            }

            var item = libraryManager.GetItemById(guid);
            if (item == null)
            {
                return BadRequest(new { error = "Item not found", itemId });
            }

            if (string.IsNullOrEmpty(item.Path))
            {
                return BadRequest(new { error = "Item has no file path", itemName = item.Name });
            }

            // Get the entry point service
            var entryPoint = AmbilightEntryPoint.Instance;
            if (entryPoint == null)
            {
                return StatusCode(500, new { error = "Ambilight service not running" });
            }

            // Trigger extraction asynchronously
            _ = Task.Run(async () => await entryPoint.TriggerExtractionAsync(guid));

            return Accepted(new AmbilightExtractResponse
            {
                ItemId = guid,
                ItemName = item.Name,
                Message = "Extraction started in background"
            });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { 
                error = ex.Message,
                type = ex.GetType().Name,
                stackTrace = ex.StackTrace 
            });
        }
    }

    /// <summary>
    /// Deletes the ambilight binary for a specific item so it can be re-extracted.
    /// </summary>
    /// <param name="itemId">The item ID.</param>
    [HttpDelete("Binary/{itemId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public ActionResult DeleteBinary([FromRoute, Required] string itemId)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(itemId) || !Guid.TryParse(itemId, out var guid))
            {
                return BadRequest(new { error = "Invalid item ID", itemId });
            }

            var config = Plugin.Instance?.Configuration;
            var dataFolder = string.IsNullOrWhiteSpace(config?.AmbilightDataFolder) ? "/data/ambilight" : config!.AmbilightDataFolder.Trim();
            var binPath = Path.Combine(dataFolder, guid.ToString("N") + ".bin");

            if (System.IO.File.Exists(binPath))
            {
                System.IO.File.Delete(binPath);
            }

            // We intentionally do not touch metadata here; the extractor service will
            // treat missing binaries as "needs extraction" on the next run.
            return NoContent();
        }
        catch (Exception ex)
        {
            return StatusCode(500, new
            {
                error = ex.Message,
                type = ex.GetType().Name,
                stackTrace = ex.StackTrace
            });
        }
    }
}

public class AmbilightStatusResponse
{
    public Guid ItemId { get; set; }
    public string? ItemName { get; set; }
    public bool HasBinary { get; set; }
    public string? BinaryPath { get; set; }
    public long BinarySize { get; set; }
    public string? ExtractionStatus { get; set; }
    public int ExtractionProgress { get; set; }
    public ulong ExtractionFramesCurrent { get; set; }
    public ulong ExtractionFramesTotal { get; set; }
}

public class AmbilightExtractResponse
{
    public Guid ItemId { get; set; }
    public string? ItemName { get; set; }
    public string? Message { get; set; }
}

public class AmbilightExtractAllResponse
{
    public int QueuedCount { get; set; }
    public string? Message { get; set; }
}
