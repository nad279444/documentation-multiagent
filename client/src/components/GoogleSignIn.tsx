import { useEffect, useRef, useState } from "react";
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

const GSI_SCRIPT_SRC = "https://accounts.google.com/gsi/client";

export default function GoogleSignIn({ onSuccess, onError }: Props) {
  const [signingIn, setSigningIn] = useState(false);
  const onSuccessRef = useRef(onSuccess);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onSuccessRef.current = onSuccess;
    onErrorRef.current = onError;
  });

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
      onSuccessRef.current(userInfo);
    } catch (error) {
      setSigningIn(false);
      onErrorRef.current(
        error instanceof Error ? error.message : "Login failed",
      );
    }
  };

  useEffect(() => {
    let cancelled = false;

    const init = () => {
      if (cancelled || !window.google) return;

      const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
      if (!clientId) {
        onErrorRef.current("Google Client ID not configured in .env.local");
        return;
      }

      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (response: any) => {
          void handleCredentialResponse(response);
        },
        auto_select: false, // Don't auto-select
      });

      const button = document.getElementById("google-signin-button");
      if (button) {
        // Fit the button to the card instead of a fixed 300px, which
        // overflows 320-375px phones.
        const width = Math.min(300, Math.max(180, button.clientWidth || 300));
        window.google.accounts.id.renderButton(button, {
          theme: "outline",
          size: "large",
          width: String(width),
        });
      }
    };

    // Reuse the GSI script across renders/remounts — reloading it on every
    // parent render made the button flicker and duplicate.
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GSI_SCRIPT_SRC}"]`,
    );
    let script: HTMLScriptElement | null = null;
    if (existing) {
      if (window.google) {
        init();
      } else {
        existing.addEventListener("load", init);
      }
    } else {
      script = document.createElement("script");
      script.src = GSI_SCRIPT_SRC;
      script.async = true;
      script.defer = true;
      script.addEventListener("load", init);
      document.head.appendChild(script);
    }

    return () => {
      cancelled = true;
      script?.removeEventListener("load", init);
      existing?.removeEventListener("load", init);
    };
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex justify-center">
        <div id="google-signin-button" className="w-full max-w-[300px]" />
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
