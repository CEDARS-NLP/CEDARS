import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "./AuthProvider";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await register(email, name, password);
      navigate("/projects");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Branding panel */}
      <div className="hidden w-1/2 flex-col justify-between bg-primary p-12 text-primary-foreground lg:flex">
        <div className="flex items-center gap-3">
          <img
            src="/cedars-logo.png"
            alt="CEDARS"
            className="h-10 w-10 brightness-0 invert"
          />
          <span className="text-xl font-semibold tracking-tight">CEDARS</span>
        </div>
        <div>
          <h1 className="text-3xl font-bold leading-tight">
            Clinical Event Detection
            <br />
            and Recording System
          </h1>
          <p className="mt-4 max-w-md text-primary-foreground/70">
            NLP-powered platform for identifying and annotating clinical events
            in electronic health records. Accelerate research with automated
            detection, human-in-the-loop review, and unified evaluation.
          </p>
        </div>
        <p className="text-sm text-primary-foreground/40">
          &copy; {new Date().getFullYear()} CEDARS-NLP
        </p>
      </div>

      {/* Form panel */}
      <div className="flex flex-1 flex-col items-center justify-center bg-background px-6">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <img
              src="/cedars-logo.png"
              alt="CEDARS"
              className="h-8 w-8 brightness-0 dark:invert"
            />
            <span className="text-lg font-semibold text-foreground">CEDARS</span>
          </div>

          <h2 className="text-2xl font-bold text-foreground">Create account</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Get started with CEDARS
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">Full name</Label>
              <Input
                id="name"
                type="text"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? "Creating account..." : "Create account"}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link
              to="/login"
              className="font-medium text-link hover:underline"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
