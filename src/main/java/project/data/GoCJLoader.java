package project.data;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Loads GoCJ task lengths, accepting whitespace or comma separated values. */
public final class GoCJLoader {
	private GoCJLoader() { }

	public static double[] load(Path path) throws IOException {
		List<Double> lengths = new ArrayList<>();
		for (String line : Files.readAllLines(path)) {
			String content = line.split("#", 2)[0].trim();
			if (content.isEmpty()) continue;
			for (String token : content.split("[,;\\s]+")) {
				lengths.add(Double.parseDouble(token));
			}
		}
		return lengths.stream().mapToDouble(Double::doubleValue).toArray();
	}
}
