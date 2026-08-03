import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { api } from "@/api/client";

export interface User {
  username: string;
  is_admin: boolean;
}

interface LoginResponse {
  message: string;
  user: User;
}

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    confirmPassword: string,
    isAdmin: boolean
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    fetchUser().finally(() => setIsLoading(false));
  }, [fetchUser]);

  const login = useCallback(async (username: string, password: string) => {
    const resp = await api.post<LoginResponse>("/auth/login", {
      username,
      password,
    });
    setUser(resp.user);
  }, []);

  const register = useCallback(
    async (
      username: string,
      password: string,
      confirmPassword: string,
      isAdmin: boolean
    ) => {
      await api.post<User>("/auth/register", {
        username,
        password,
        confirm_password: confirmPassword,
        is_admin: isAdmin,
      });
      await login(username, password);
    },
    [login]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } catch {
      // Ignore errors during logout
    }
    setUser(null);
  }, []);

  return (
    <AuthContext value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
