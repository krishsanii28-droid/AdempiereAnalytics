package org.insightai.adempiere;

import java.util.concurrent.Callable;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

import javafx.application.Platform;
import javafx.beans.value.ChangeListener;
import javafx.beans.value.ObservableValue;
import javafx.concurrent.Worker;
import javafx.embed.swing.JFXPanel;
import javafx.scene.Scene;
import javafx.scene.web.WebEngine;
import javafx.scene.web.WebView;

/**
 * A Swing component showing a web page with JavaFX WebView.
 * All JavaFX use is kept in this class, so the form can still load on a runtime without JavaFX.
 */
class InsightAIWebPanel extends JFXPanel {
	private static final long serialVersionUID = 1L;

	private volatile WebEngine engine;
	private volatile boolean loaded;

	InsightAIWebPanel() {
		// Creating a JFXPanel starts the JavaFX toolkit. It must outlive this window, or opening
		// InsightAI a second time in the same ADempiere session would find the toolkit shut down.
		Platform.setImplicitExit(false);
		Platform.runLater(new Runnable() {
			@Override
			public void run() {
				WebView view = new WebView();
				view.setContextMenuEnabled(false);
				engine = view.getEngine();
				engine.getLoadWorker().stateProperty().addListener(new ChangeListener<Worker.State>() {
					@Override
					public void changed(ObservableValue<? extends Worker.State> value, Worker.State before, Worker.State now) {
						loaded = now == Worker.State.SUCCEEDED;
					}
				});
				setScene(new Scene(view));
			}
		});
	}

	void load(final String url) {
		loaded = false;
		Platform.runLater(new Runnable() {
			@Override
			public void run() {
				engine.load(url);
			}
		});
	}

	boolean isLoaded() {
		return loaded;
	}

	String evaluate(final String script) throws Exception {
		FutureTask<String> task = new FutureTask<String>(new Callable<String>() {
			@Override
			public String call() {
				return String.valueOf(engine.executeScript(script));
			}
		});
		Platform.runLater(task);
		return task.get(10, TimeUnit.SECONDS);
	}

	void close() {
		Platform.runLater(new Runnable() {
			@Override
			public void run() {
				if (engine != null)
					engine.load(null);      // stops scripts and timers of the page
			}
		});
	}
}
