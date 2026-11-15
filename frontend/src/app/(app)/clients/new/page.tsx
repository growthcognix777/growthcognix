"use client";
import { ClientForm } from "@/components/ClientForm";
import { PageHeader } from "@/components/ui";
export default function NewClient() {
  return <div className="mx-auto max-w-4xl"><PageHeader title="New client" subtitle="Capture the essentials now — you can add products and documents next." /><ClientForm /></div>;
}
