using Jellyfin.Plugin.Ambilight.Server;
using MediaBrowser.Controller;
using MediaBrowser.Controller.Plugins;
using Microsoft.Extensions.DependencyInjection;

namespace Jellyfin.Plugin.Ambilight;

/// <summary>
/// Registers the Ambilight background service with Jellyfin's DI container.
/// </summary>
public class AmbilightServiceRegistrator : IPluginServiceRegistrator
{
    /// <inheritdoc />
    public void RegisterServices(IServiceCollection serviceCollection, IServerApplicationHost applicationHost)
    {
        serviceCollection.AddHostedService<AmbilightEntryPoint>();
    }
}
