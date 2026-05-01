using System;
using System.Collections;
using System.Linq;
using System.Collections.Generic;
using System.Threading.Tasks;
using BS_Utils.Gameplay;
using HMUI;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using Zenject;
using BeatSaberMarkupLanguage;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Components;
using BeatSaberMarkupLanguage.ViewControllers;
using JBSLViewer.Models;
using JBSLViewer.Models.JBSL;

namespace JBSLViewer.Views
{
    [HotReload]
    public class LeaderboardMainViewController : BSMLAutomaticViewController
    {
        private static readonly Color32 SelfColor = new Color32(90, 210, 255, 255);
        private static readonly Color32 ValidColor = new Color32(110, 255, 145, 255);
        private static readonly Color32 InvalidColor = new Color32(150, 150, 150, 255);

        public bool _init = false;
        public int _page = 0;
        private Task<string> _selfSidTask;
        private string _selfSid;

        [Inject]
        private readonly ActiveLeague _activeLeague;
        [Inject]
        private readonly Leaderboard _leaderboard;
        [Inject]
        private readonly LeaderboardPanelViewController _leaderboardPanelViewController;
        [Inject]
        private readonly VirtualLeagueService _virtualLeagueService;

        [UIComponent("list")]
        public readonly CustomCellListTableData _list;

        [UIValue("entries")]
        public readonly List<object> _records = new List<object>();

        [UIComponent("Title")]
        private readonly TextMeshProUGUI _title;

        [UIComponent("TitileBar")]
        private readonly Backgroundable _titileBar;

        [UIAction("PageUp")]
        public void PageUp()
        {
            this._page--;
            this.SetRecords();
        }

        [UIAction("PageDown")]
        public void PageDown()
        {
            this._page++;
            this.SetRecords();
        }

        [UIAction("#post-parse")]
        public void PostParse()
        {
            this._init = true;
            var color = new Color32(228, 144, 50, 255);
            this._titileBar.background.material = Utilities.ImageResources.NoGlowMat;
            var imageView = this._titileBar.background as ImageView;
            imageView.color = color;
            imageView.color0 = color;
            imageView.color1 = color;
            imageView._skew = 0.18f;
            imageView.gradient = true;
            imageView.SetVerticesDirty();
            _ = JBSLHoverHintController.Instance;
            this.SetTitle();
        }

        public void SetTitle(string title = null)
        {
            if (!this._init)
                return;
            if (title == null)
                this._title.text = this._leaderboardPanelViewController.GetLeaderboardName();
            else
                this._title.text = title;
            this._page = 0;
            if (this._leaderboardPanelViewController.LeaderboardValue == "0")
                this._title.fontSize = 6f;
            else
                this._title.fontSize = 3f;
            this.SetRecords();
        }

        public bool TryRefreshCurrentUserSid()
        {
            if (!string.IsNullOrEmpty(this._selfSid))
                return false;

            if (this._selfSidTask == null)
                this._selfSidTask = FetchCurrentUserSidAsync();
            if (!this._selfSidTask.IsCompleted)
                return false;

            string sid;
            try
            {
                sid = this._selfSidTask.GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
                this._selfSidTask = null;
                return false;
            }

            if (string.IsNullOrEmpty(sid) || string.Equals(this._selfSid, sid, StringComparison.Ordinal))
            {
                if (string.IsNullOrEmpty(sid))
                    this._selfSidTask = null;
                return false;
            }

            this._selfSid = sid;
            return true;
        }

        private static async Task<string> FetchCurrentUserSidAsync()
        {
            var userInfo = await GetUserInfo.GetUserAsync();
            return userInfo?.platformUserId;
        }

        public void SetRecords()
        {
            if (!this._init || this._list == null)
                return;

            this.TryRefreshCurrentUserSid();
            this._records.Clear();
            this._list.tableView.ReloadData();
            if (LeaderboardPanelViewController.AllResetSemaphore.CurrentCount == 0 || LeaderboardPanelViewController.SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            if (!int.TryParse(this._leaderboardPanelViewController.JBSLLeagueValue, out var leagueID))
                return;
            if (!int.TryParse(this._leaderboardPanelViewController.LeaderboardValue, out var index))
                return;

            var displayLeaderboard = this._virtualLeagueService.GetLeaderboardForDisplay(leagueID);
            if (displayLeaderboard == null)
                displayLeaderboard = this._leaderboard.GetLeaderboardData(leagueID);
            if (displayLeaderboard == null)
                return;

            List<Score> scores;
            if (index == 0)
                scores = displayLeaderboard.total_rank;
            else
                scores = index - 1 >= 0 && index - 1 < (displayLeaderboard.maps?.Count ?? 0) ? displayLeaderboard.maps[index - 1].scores : null;
            if (scores == null)
                return;

            var maxValid = Math.Max(this._activeLeague.GetLeagueMaxValid(leagueID), 0);
            var validityContext = this._leaderboard.BuildValidityContext(displayLeaderboard, maxValid);
            var totalMaxPos = Leaderboard.BuildTotalMaxPos(Leaderboard.InferLeagueBasePosFromMaps(displayLeaderboard), maxValid);
            var maxPage = Math.Max(0, (scores.Count - 1) / 10);
            if (maxPage < this._page)
                this._page = maxPage;
            if (this._page < 0)
                this._page = 0;

            if (index == 0)
            {
                foreach (var score in scores.Skip(this._page * 10).Take(10))
                {
                    validityContext.TryGetSummary(score.sid, out var summary);
                    var record = new Record(
                        $"#{score.standing}",
                        score.name ?? string.Empty,
                        score.pos.ToString(),
                        FormatTotalRatio(score.pos, totalMaxPos),
                        summary?.ValidCount.ToString() ?? "0",
                        $"{score.acc:F2}%",
                        this.IsCurrentUser(score.sid),
                        false,
                        true,
                        summary?.PosTooltip,
                        summary?.ValidTooltip,
                        summary?.AccTooltip);
                    this._records.Add(record);
                }
            }
            else
            {
                var mapIndex = index - 1;
                foreach (var score in scores.Skip(this._page * 10).Take(10))
                {
                    var isValid = validityContext.IsValidScore(mapIndex, score.sid);
                    var record = new Record(
                        $"#{score.standing}",
                        score.name ?? string.Empty,
                        score.pos.ToString(),
                        isValid ? "✓" : "-",
                        $"{score.acc:F2}%",
                        FormatMiss(score.miss),
                        this.IsCurrentUser(score.sid),
                        isValid,
                        false,
                        null,
                        null,
                        null);
                    this._records.Add(record);
                }
            }

            this._list.tableView.ReloadData();
        }

        private bool IsCurrentUser(string sid)
        {
            return !string.IsNullOrEmpty(this._selfSid) && string.Equals(this._selfSid, sid, StringComparison.Ordinal);
        }

        private static string FormatTotalRatio(int totalPos, int totalMaxPos)
        {
            if (totalMaxPos <= 0)
                return "(0.00 %)";
            if (totalPos >= totalMaxPos)
                return "MAX";

            var ratio = (float)totalPos / totalMaxPos * 100f;
            return $"({ratio:F2} %)";
        }

        private static string FormatMiss(int miss)
        {
            return miss <= 0 ? "FC" : miss.ToString();
        }

        public class Record
        {
            [UIValue("standing")]
            public string _standing { get; }

            [UIValue("name")]
            public string _name { get; }

            [UIValue("pos")]
            public string _pos { get; }

            [UIValue("ratio_or_miss")]
            public string _ratioOrMiss { get; }

            [UIValue("valid")]
            public string _valid { get; }

            [UIValue("acc")]
            public string _acc { get; }

            private readonly bool _isCurrentUser;
            private readonly bool _isMapValid;
            private readonly bool _isTotalRecord;
            private readonly string _posTooltip;
            private readonly string _validTooltip;
            private readonly string _accTooltip;

            [UIComponent("StandingText")]
            private readonly TextMeshProUGUI _standingText;

            [UIComponent("NameText")]
            private readonly TextMeshProUGUI _nameText;

            [UIComponent("PosText")]
            private readonly TextMeshProUGUI _posText;

            [UIComponent("RatioOrMissText")]
            private readonly TextMeshProUGUI _ratioOrMissText;

            [UIComponent("ValidText")]
            private readonly TextMeshProUGUI _validText;

            [UIComponent("AccText")]
            private readonly TextMeshProUGUI _accText;

            public Record(string standing, string name, string pos, string ratioOrMiss, string valid, string acc, bool isCurrentUser, bool isMapValid, bool isTotalRecord, string posTooltip, string validTooltip, string accTooltip)
            {
                this._standing = standing;
                this._name = name;
                this._pos = pos;
                this._ratioOrMiss = ratioOrMiss;
                this._valid = valid;
                this._acc = acc;
                this._isCurrentUser = isCurrentUser;
                this._isMapValid = isMapValid;
                this._isTotalRecord = isTotalRecord;
                this._posTooltip = posTooltip;
                this._validTooltip = validTooltip;
                this._accTooltip = accTooltip;
            }

            [UIAction("#post-parse")]
            public void PostParse()
            {
                Color mainColor = this._isCurrentUser ? (Color)SelfColor : Color.white;
                ApplyColor(this._standingText, mainColor);
                ApplyColor(this._nameText, mainColor);
                ApplyColor(this._posText, mainColor);
                if (this._isTotalRecord)
                {
                    ApplyColor(this._ratioOrMissText, mainColor);
                    ApplyColor(this._validText, mainColor);
                    ApplyColor(this._accText, mainColor);
                }
                else
                {
                    ApplyColor(this._ratioOrMissText, this._isMapValid ? ValidColor : InvalidColor);
                    ApplyColor(this._validText, mainColor);
                    ApplyColor(this._accText, mainColor);
                }

                AddHoverHint(this._posText, this._posTooltip);
                AddHoverHint(this._validText, this._validTooltip);
                AddHoverHint(this._accText, this._accTooltip);
            }

            private static void ApplyColor(TMP_Text text, Color color)
            {
                if (text != null)
                    text.color = color;
            }

            private static void AddHoverHint(TMP_Text text, string tooltip)
            {
                if (text == null)
                    return;

                var legacyHoverHint = text.GetComponent<HoverHint>();
                if (legacyHoverHint != null)
                {
                    legacyHoverHint.enabled = false;
                    Destroy(legacyHoverHint);
                }

                var hoverHint = text.GetComponent<JBSLHoverHint>();
                if (hoverHint == null)
                    hoverHint = text.gameObject.AddComponent<JBSLHoverHint>();

                var hasTooltip = !string.IsNullOrWhiteSpace(tooltip);
                text.raycastTarget = hasTooltip;
                hoverHint.enabled = hasTooltip;
                hoverHint.text = hasTooltip ? tooltip : null;
            }
        }
    }

    public class JBSLHoverHint : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
    {
        private readonly Vector3[] _worldCornersTemp = new Vector3[4];

        public string text { get; set; }

        public Vector2 size
        {
            get
            {
                return ((RectTransform)this.transform).rect.size;
            }
        }

        public Vector3 worldCenter
        {
            get
            {
                ((RectTransform)this.transform).GetWorldCorners(this._worldCornersTemp);
                var center = Vector3.zero;
                for (var i = 0; i < this._worldCornersTemp.Length; i++)
                    center += this._worldCornersTemp[i];
                return center * 0.25f;
            }
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            JBSLHoverHintController.Instance?.ShowHint(this);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            var controller = JBSLHoverHintController.InstanceOrNull;
            if (controller == null)
                return;

            if (eventData.currentInputModule == null || !eventData.currentInputModule.enabled)
                controller.HideHintInstant();
            else
                controller.HideHint();
        }

        public void OnDisable()
        {
            JBSLHoverHintController.InstanceOrNull?.HideHintInstant();
        }
    }

    public class JBSLHoverHintController : MonoBehaviour
    {
        private const float ShowHintDelay = 0.6f;
        private const float HideHintDelay = 0.3f;
        private static JBSLHoverHintController _instance;

        private HoverHintPanel _hoverHintPanelPrefab;
        private HoverHintPanel _hoverHintPanel;
        private bool _isHiding;
        private bool _isShown;

        public static JBSLHoverHintController Instance
        {
            get
            {
                if (_instance != null)
                    return _instance;

                var controllers = Resources.FindObjectsOfTypeAll<JBSLHoverHintController>();
                if (controllers != null && controllers.Length > 0)
                {
                    _instance = controllers[0];
                    return _instance;
                }

                var baseController = BeatSaberUI.HoverHintController;
                if (baseController == null)
                    return null;

                var gameObject = new GameObject("JBSLHoverHintController");
                gameObject.transform.SetParent(baseController.transform, false);

                _instance = gameObject.AddComponent<JBSLHoverHintController>();
                _instance.Initialize(baseController);
                return _instance;
            }
        }

        public static JBSLHoverHintController InstanceOrNull => _instance;

        public void Initialize(HoverHintController baseController)
        {
            if (this._hoverHintPanel != null)
                return;

            this._hoverHintPanelPrefab = baseController._hoverHintPanel ?? baseController._hoverHintPanelPrefab;
            if (this._hoverHintPanelPrefab == null)
                return;

            this._hoverHintPanel = Instantiate(this._hoverHintPanelPrefab, this.transform);
            this._hoverHintPanel.Hide();
            this._isShown = false;
        }

        public void OnDestroy()
        {
            if (_instance == this)
                _instance = null;
        }

        public void ShowHint(JBSLHoverHint hoverHint)
        {
            if (hoverHint == null || string.IsNullOrEmpty(hoverHint.text))
                return;

            if (this._hoverHintPanel == null)
                this.Initialize(BeatSaberUI.HoverHintController);
            if (this._hoverHintPanel == null)
                return;

            this._isHiding = false;
            this.StopAllCoroutines();
            if (this._isShown)
            {
                this.SetupAndShowHintPanel(hoverHint);
                return;
            }

            this.StartCoroutine(this.ShowHintAfterDelay(hoverHint, ShowHintDelay));
        }

        public void HideHint()
        {
            if (this._isHiding || this._hoverHintPanel == null)
                return;

            this.StopAllCoroutines();
            this.StartCoroutine(this.HideHintAfterDelay(HideHintDelay));
        }

        public void HideHintInstant()
        {
            this.StopAllCoroutines();
            if (this._hoverHintPanel == null || !this._isShown)
                return;

            this._hoverHintPanel.Hide();
            this._isShown = false;
            this._isHiding = false;
        }

        private IEnumerator ShowHintAfterDelay(JBSLHoverHint hoverHint, float delay)
        {
            yield return new WaitForSeconds(delay);
            if (hoverHint != null)
                this.SetupAndShowHintPanel(hoverHint);
        }

        private IEnumerator HideHintAfterDelay(float delay)
        {
            this._isHiding = true;
            yield return new WaitForSeconds(delay);
            if (this._hoverHintPanel != null)
                this._hoverHintPanel.Hide();
            this._isShown = false;
            this._isHiding = false;
        }

        private void SetupAndShowHintPanel(JBSLHoverHint hoverHint)
        {
            var rectTransform = (RectTransform)GetScreenTransformForHoverHint(hoverHint.transform);
            var spawnRect = default(Rect);
            spawnRect.size = hoverHint.size;
            spawnRect.position = rectTransform.InverseTransformPoint(hoverHint.worldCenter);
            spawnRect.position -= spawnRect.size * 0.5f;
            this.ShowPanel(hoverHint.text, rectTransform, rectTransform.rect.size, spawnRect);
        }

        private void ShowPanel(string text, RectTransform parent, Vector2 containerSize, Rect spawnRect)
        {
            var panelTransform = (RectTransform)this._hoverHintPanel.transform;
            panelTransform.SetParent(parent, false);
            panelTransform.SetAsLastSibling();
            panelTransform.localScale = Vector3.one;
            panelTransform.localRotation = Quaternion.identity;

            this._hoverHintPanel.gameObject.SetActive(true);

            var textComponent = this._hoverHintPanel._text;
            textComponent.text = text;
            textComponent.ForceMeshUpdate();

            var panelTextSize = (Vector2)textComponent.bounds.size;
            var panelSize = panelTextSize + this._hoverHintPanel._padding;
            panelTransform.sizeDelta = panelSize;
            panelTransform.anchoredPosition = CalculatePanelPosition(
                containerSize,
                spawnRect,
                panelSize,
                this._hoverHintPanel._containerPadding,
                this._hoverHintPanel._separator);

            var localPosition = panelTransform.localPosition;
            localPosition.z = -this._hoverHintPanel._zOffset;
            panelTransform.localPosition = localPosition;

            this._isShown = true;
            this._isHiding = false;
        }

        private static Vector2 CalculatePanelPosition(Vector2 containerSize, Rect spawnRect, Vector2 panelSize, Vector2 containerPadding, float separator)
        {
            var minX = -containerSize.x * 0.5f + containerPadding.x + panelSize.x * 0.5f;
            var maxX = containerSize.x * 0.5f - containerPadding.x - panelSize.x * 0.5f;
            var x = Mathf.Clamp(spawnRect.center.x, minX, maxX);

            var aboveY = spawnRect.center.y + spawnRect.size.y * 0.5f + separator + panelSize.y * 0.5f;
            return new Vector2(x, aboveY);
        }

        private static Transform GetScreenTransformForHoverHint(Transform hoverHintTransform)
        {
            var transform = hoverHintTransform;
            while (transform != null)
            {
                if (transform.GetComponent<Canvas>() != null && transform.GetComponent<HMUI.Screen>() != null)
                    return transform;
                transform = transform.parent;
            }

            return hoverHintTransform;
        }
    }
}
