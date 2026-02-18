// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

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
