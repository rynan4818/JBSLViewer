using System;
using System.Collections.Concurrent;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using SiraUtil.Zenject;
using JBSLViewer.Configuration;
using JBSLViewer.Models.ScoreSaber;

namespace JBSLViewer.Models
{
    public class  SaveDataJson
    {
        public ConcurrentDictionary<string, LeaderboardInfoJson> LeaderboardInfos { get; set; } = new ConcurrentDictionary<string, LeaderboardInfoJson>();
    }
    public class SaveData : IAsyncInitializable, IDisposable
    {
        private bool disposedValue;
        public static SemaphoreSlim RecordsSemaphore = new SemaphoreSlim(1, 1);
        public bool _init;
        public SaveDataJson _saveData = new SaveDataJson();

        public async Task InitializeAsync(CancellationToken token)
        {
            await this.InitSaveDataAsync();
            Plugin.OnPluginExit += BackupSaveData; //ファイルの書き込み処理はDisposeのときでは間に合わない
        }
        public void AddLeaderboardInfo(string lid, LeaderboardInfoJson leaderboardInfoData)
        {
            if (!this._init)
                return;
            if (lid == null || leaderboardInfoData == null)
                return;
            if (this._saveData.LeaderboardInfos.ContainsKey(lid))
                this._saveData.LeaderboardInfos[lid] = leaderboardInfoData;
            else
                this._saveData.LeaderboardInfos.TryAdd(lid, leaderboardInfoData);
        }

        public async Task InitSaveDataAsync()
        {
            this._init = false;
            this._saveData = await this.ReadRecordFileAsync(PluginConfig.Instance.SaveDataFile);
            if (this._saveData == null)
            {
                Plugin.Log?.Info("Restoring savedata backup");
                this._saveData = await this.ReadRecordFileAsync(Path.ChangeExtension(PluginConfig.Instance.SaveDataFile, ".bak"));
                if (this._saveData == null)
                    this._saveData = new SaveDataJson();
                await this.WriteSaveDataAsync();
            }
            this._init = true;
        }
        public async Task WriteSaveDataAsync()
        {
            try
            {
                var serialized = await Task.Run(() => JsonConvert.SerializeObject(this._saveData, Formatting.None)).ConfigureAwait(false);
                if (!await this.WriteAllTextAsync(PluginConfig.Instance.SaveDataFile, serialized))
                    throw new Exception("Failed save mapdata");
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
            }
        }
        public void WriteSaveData()
        {
            try
            {
                var serialized = JsonConvert.SerializeObject(this._saveData, Formatting.None);
                File.WriteAllText(PluginConfig.Instance.SaveDataFile, serialized);
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
            }
        }
        public void BackupSaveData()
        {
            if (!this._init)
                return;
            if (!File.Exists(PluginConfig.Instance.SaveDataFile))
                return;
            Plugin.Log?.Info("Play data backup");
            if (!this.CheckSaveDataFile())
            {
                this.WriteSaveData();
                if (!this.CheckSaveDataFile())
                    return;
            }
            var backupFile = Path.ChangeExtension(PluginConfig.Instance.SaveDataFile, ".bak");
            try
            {
                if (File.Exists(backupFile))
                {
                    if (new FileInfo(PluginConfig.Instance.SaveDataFile).Length > new FileInfo(backupFile).Length)
                        File.Copy(PluginConfig.Instance.SaveDataFile, backupFile, true);
                    else
                        Plugin.Log?.Info("Nothing backup");
                }
                else
                {
                    File.Copy(PluginConfig.Instance.SaveDataFile, backupFile);
                }
            }
            catch (IOException ex)
            {
                Plugin.Log?.Error(ex.ToString());
            }
        }
        public bool CheckSaveDataFile()
        {
            try
            {
                var text = File.ReadAllText(PluginConfig.Instance.SaveDataFile);
                var result = JsonConvert.DeserializeObject<SaveDataJson>(text);
                if (result == null)
                    return false;
                else
                    return true;
            }
            catch (Exception e)
            {
                Plugin.Log?.Error(e.ToString());
                return false;
            }
        }
        public async Task<SaveDataJson> ReadRecordFileAsync(string path)
        {
            SaveDataJson result;
            var json = await this.ReadAllTextAsync(path);
            try
            {
                if (json == null)
                    throw new JsonReaderException($"Json file error {path}");
                result = JsonConvert.DeserializeObject<SaveDataJson>(json);
                if (result == null)
                    throw new JsonReaderException($"Empty json {path}");
            }
            catch (JsonException ex)
            {
                Plugin.Log?.Error(ex.ToString());
                result = null;
            }
            return result;
        }
        public async Task<string> ReadAllTextAsync(string path)
        {
            var fileInfo = new FileInfo(path);
            if (!fileInfo.Exists || fileInfo.Length == 0)
            {
                Plugin.Log?.Info($"File not found : {path}");
                return null;
            }
            string result;
            await RecordsSemaphore.WaitAsync();
            try
            {
                using (var sr = new StreamReader(path))
                {
                    result = await sr.ReadToEndAsync();
                }
            }
            catch (Exception e)
            {
                Plugin.Log?.Error(e.ToString());
                result = null;
            }
            finally
            {
                RecordsSemaphore.Release();
            }
            return result;
        }
        public async Task<bool> WriteAllTextAsync(string path, string contents)
        {
            bool result;
            await RecordsSemaphore.WaitAsync();
            try
            {
                using (var sw = new StreamWriter(path))
                {
                    await sw.WriteAsync(contents);
                }
                result = true;
            }
            catch (Exception e)
            {
                Plugin.Log?.Error(e.ToString());
                result = false;
            }
            finally
            {
                RecordsSemaphore.Release();
            }
            return result;
        }

        protected virtual void Dispose(bool disposing)
        {
            if (!disposedValue)
            {
                if (disposing)
                {
                    // TODO: マネージド状態を破棄します (マネージド オブジェクト)
                    Plugin.OnPluginExit -= BackupSaveData;
                }

                // TODO: アンマネージド リソース (アンマネージド オブジェクト) を解放し、ファイナライザーをオーバーライドします
                // TODO: 大きなフィールドを null に設定します
                disposedValue = true;
            }
        }

        // // TODO: 'Dispose(bool disposing)' にアンマネージド リソースを解放するコードが含まれる場合にのみ、ファイナライザーをオーバーライドします
        // ~MapData()
        // {
        //     // このコードを変更しないでください。クリーンアップ コードを 'Dispose(bool disposing)' メソッドに記述します
        //     Dispose(disposing: false);
        // }

        public void Dispose()
        {
            // このコードを変更しないでください。クリーンアップ コードを 'Dispose(bool disposing)' メソッドに記述します
            Dispose(disposing: true);
            GC.SuppressFinalize(this);
        }
    }
}
