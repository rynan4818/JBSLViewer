using System;
namespace JBSLViewer.Qualifier.Core {
    public sealed class ScoreServerEndpoint {
        public string NormalizedUrl { get; private set; }
        public Uri Uri { get; private set; }
        public static ScoreServerEndpoint Parse(string value,bool allowDevelopmentHttp) {
            Uri uri;
            if(!System.Uri.TryCreate(value,UriKind.Absolute,out uri) || !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment)) throw new ArgumentException("Invalid score server URL");
            var scheme=uri.Scheme.ToLowerInvariant(); var host=uri.Host.ToLowerInvariant();
            if(scheme!="https" && !(scheme=="http" && allowDevelopmentHttp && (host=="127.0.0.1" || host=="localhost"))) throw new ArgumentException("HTTPS is required except explicitly enabled HTTP loopback");
            var path=uri.AbsolutePath.TrimEnd('/')+"/";
            var normalized=scheme+"://"+host+":"+uri.Port+path;
            // Include the effective port in the identity even when Uri.ToString omits its default.
            return new ScoreServerEndpoint { NormalizedUrl=normalized, Uri=new Uri(normalized) };
        }
        public Uri Resolve(string relative) { return new Uri(Uri,relative.TrimStart('/')); }
        public override string ToString() { return NormalizedUrl; }
    }
}
