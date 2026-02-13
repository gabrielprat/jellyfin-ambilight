using System;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight.Server;
using MediaBrowser.Controller.Library;
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

            var status = new AmbilightStatusResponse
            {
                ItemId = guid,
                ItemName = item.Name,
                HasBinary = System.IO.File.Exists(binPath),
                BinaryPath = binPath,
                BinarySize = System.IO.File.Exists(binPath) ? new FileInfo(binPath).Length : 0
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
}

public class AmbilightStatusResponse
{
    public Guid ItemId { get; set; }
    public string? ItemName { get; set; }
    public bool HasBinary { get; set; }
    public string? BinaryPath { get; set; }
    public long BinarySize { get; set; }
}

public class AmbilightExtractResponse
{
    public Guid ItemId { get; set; }
    public string? ItemName { get; set; }
    public string? Message { get; set; }
}
