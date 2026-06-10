import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
} from "./card";

describe("Card", () => {
  it("отображает составной блок карточки", () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>Заголовок</CardTitle>
          <CardDescription>Описание</CardDescription>
        </CardHeader>
        <CardContent>Контент</CardContent>
        <CardFooter>Подвал</CardFooter>
      </Card>,
    );
    expect(screen.getByTestId("card")).toHaveClass("rounded-xl");
    expect(screen.getByText("Заголовок")).toBeInTheDocument();
    expect(screen.getByText("Описание")).toBeInTheDocument();
    expect(screen.getByText("Контент")).toBeInTheDocument();
    expect(screen.getByText("Подвал")).toBeInTheDocument();
  });

  it("пробрасывает ref и className для всех частей", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <Card ref={ref} className="card-extra">
        body
      </Card>,
    );
    expect(ref.current).toBeInstanceOf(HTMLDivElement);
    expect(ref.current).toHaveClass("card-extra");
  });

  it("применяет специфичные классы заголовка и описания", () => {
    render(
      <>
        <CardTitle data-testid="title">t</CardTitle>
        <CardDescription data-testid="desc">d</CardDescription>
      </>,
    );
    expect(screen.getByTestId("title")).toHaveClass("font-semibold");
    expect(screen.getByTestId("desc")).toHaveClass("text-muted-foreground");
  });
});
