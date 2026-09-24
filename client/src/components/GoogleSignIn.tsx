import { useEffect, useState } from "react";
import { setToken, verifyToken } from "../lib/auth";

interface Props {
  onSuccess: (userInfo: any) => void;
  onError: (error: string) => void;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: any) => void;
          renderButton: (element: HTMLElement, options: any) => void;
          cancel: () => void;
        };
      };
    };
  }
}

export default function GoogleSignIn({ onSuccess, onError }: Props) {
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    // Load Google Sign-In script
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;

    script.onload = () => {
      if (!window.google) return;

      const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
      if (!clientId) {
        onError("Google Client ID not configured in .env.local");
        return;
      }

      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: handleCredentialResponse,
        auto_select: false, // Don't auto-select
      });

      const button = document.getElementById("google-signin-button");
      if (button) {
        window.google.accounts.id.renderButton(button, {
          theme: "outline",
          size: "large",
          width: "300",
        });
      }
    };

    document.head.appendChild(script);

    return () => {
      if (document.head.contains(script)) {
        document.head.removeChild(script);
      }
    };
  }, [onSuccess, onError]);

  const handleCredentialResponse = async (response: any) => {
    setSigningIn(true);
    try {
      // response.credential is the JWT id_token from Google
      const idToken = response.credential;

      // Verify with backend (backend verifies with Google's public keys)
      const userInfo = await verifyToken(idToken);

      // Store token in sessionStorage
      setToken(idToken);

      // Call success callback
      onSuccess(userInfo);
    } catch (error) {
      setSigningIn(false);
      onError(error instanceof Error ? error.message : "Login failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-center">
        <div id="google-signin-button"></div>
      </div>
      <div className={`rounded-xl border px-4 py-3 text-center text-sm font-medium ${
        signingIn
          ? "border-sky-200 bg-sky-50 text-sky-800"
          : "border-slate-200 bg-slate-50 text-slate-500"
      }`}>
        {signingIn
          ? "Please wait patiently while we sign you in."
          : "After selecting your Google account, please wait patiently while we verify your access."}
      </div>
    </div>
  );
}
