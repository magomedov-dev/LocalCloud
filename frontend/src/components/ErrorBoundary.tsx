import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

/**
 * Свойства компонента `ErrorBoundary`.
 *
 * Принимает дочерние элементы, которые должны быть защищены
 * от ошибок во время рендера.
 */
interface Props {
  children: ReactNode;
}

/**
 * Внутреннее состояние компонента `ErrorBoundary`.
 *
 * Хранит ошибку, если она была перехвачена.
 */
interface State {
  error: Error | null;
}

/**
 * Компонент для перехвата ошибок в дереве React-компонентов.
 *
 * Отображает fallback-интерфейс, если во время рендера дочерних компонентов
 * произошла ошибка. Пользователь может сбросить состояние ошибки
 * и попробовать отрендерить содержимое повторно.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  /**
   * Обновляет состояние при возникновении ошибки.
   *
   * Вызывается React автоматически после ошибки в дочернем компоненте.
   */
  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
          <p className="text-lg font-medium">Что-то пошло не так</p>
          <p className="text-muted-foreground max-w-sm text-sm">
            {this.state.error.message || "Произошла непредвиденная ошибка."}
          </p>
          <Button variant="outline" onClick={() => this.setState({ error: null })}>
            Попробовать снова
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
