"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, setToken } from "@/lib/api";

interface AuthState {
  email: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthState>({
  email: null,
  loading: true,
  login: async () => {},
  register: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // token presence check (validation happens server-side per request)
    const t = localStorage.getItem("medintel_token");
    setEmail(t ? localStorage.getItem("medintel_email") : null);
    setLoading(false);
  }, []);

  const login = useCallback(
    async (em: string, pw: string) => {
      const res = await api.auth.login(em, pw);
      setToken(res.access_token);
      localStorage.setItem("medintel_email", em);
      setEmail(em);
      router.push("/dashboard");
    },
    [router]
  );

  const register = useCallback(
    async (em: string, pw: string) => {
      await api.auth.register(em, pw);
      await login(em, pw);
    },
    [login]
  );

  const logout = useCallback(() => {
    setToken(null);
    localStorage.removeItem("medintel_email");
    setEmail(null);
    router.push("/login");
  }, [router]);

  return (
    <Ctx.Provider value={{ email, loading, login, register, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  return useContext(Ctx);
}
