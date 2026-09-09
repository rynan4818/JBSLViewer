using IPA;
using IPA.Config;
using IPA.Config.Stores;
using SiraUtil.Zenject;
using IPALogger = IPA.Logging.Logger;
using JBSLViewer.Installers;
using System;
using HarmonyLib;

namespace JBSLViewer
{
    [Plugin(RuntimeOptions.SingleStartInit)]
    public class Plugin
    {
        internal static Plugin Instance { get; private set; }
        internal static IPALogger Log { get; private set; }
        public static event Action OnPluginExit;
        private Harmony _harmony;
        internal static bool QualifierHooksReady { get; private set; }

        [Init]
        /// <summary>
        /// IPAによってプラグインが最初にロードされたときに呼び出される（ゲームが開始されたとき、またはプラグインが無効な状態で開始された場合は有効化されたときのいずれか）
        /// [Init]コンストラクタを使用するメソッドや、InitWithConfigなどの通常のメソッドの前に呼び出されるメソッド
        /// [Init]は1つのコンストラクタにのみ使用してください
        /// </summary>
        public void Init(IPALogger logger, Config conf, Zenjector zenjector)
        {
            Instance = this;
            Log = logger;
            Log?.Debug("Logger initialized.");

            //BSIPAのConfigを使用する場合はコメントを外します
            Configuration.PluginConfig.Instance = conf.Generated<Configuration.PluginConfig>();
            Log?.Debug("Config loaded");

            //使用するZenjectのインストーラーのコメントを外します
            zenjector.Install<JBSLViewerAppInstaller>(Location.App);
            zenjector.Install<JBSLViewerMenuInstaller>(Location.Menu);
            zenjector.Install<JBSLViewerPlayerInstaller>(Location.StandardPlayer);
        }
        [OnStart]
        public void OnApplicationStart()
        {
            Log.Debug("OnApplicationStart");
            _harmony = new Harmony("JBSLViewer.Qualifier");
            try
            {
                _harmony.PatchAll(typeof(Plugin).Assembly);
                QualifierHooksReady = true;
            }
            catch (Exception ex)
            {
                _harmony.UnpatchSelf();
                QualifierHooksReady = false;
                Log.Error("Qualifier hooks could not be installed: " + ex.GetType().Name);
            }
        }

        [OnExit]
        public void OnApplicationQuit()
        {
            Log.Debug("OnApplicationQuit");
            OnPluginExit?.Invoke();
            _harmony?.UnpatchSelf();
        }
    }
}
