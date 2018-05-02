"""
Model definition.
"""
import tensorflow as tf
import numpy as np
import time
from layers import WindowLayer, HiddenLayers, MDNLayer
import utilities
import matplotlib.pyplot as plt

class SynthesisModel(object):
	def __init__(self, n_layers=1, batch_size=100, num_units=100, K=10, M=20, n_chars=80, str_len=0, sampling_bias = 0.0):
		# Store parameters
		self.n_layers = n_layers
		self.batch_size = batch_size
		self.n_chars = n_chars
		self.n_units = num_units
		self.n_gaussians_window = K
		self.n_gaussians_mdn = M
		self.bias = sampling_bias

		# Define the computational graph here
		self.graph = tf.Graph()
		with self.graph.as_default():
			# Create placeholder for input of dimension [batch_size, timesteps, 3]
			inputs = tf.placeholder(tf.float32, [None, None, 3])
			# Create placeholder for expected output of dimension [batch_size, timesteps, 3]
			output = tf.placeholder(tf.float32, [None, None, 3])
			# Create placeholder for one-hot encoded string of dimension [batch_size, seq_length, n_chars]
			C = tf.placeholder(tf.float32, [None, None, self.n_chars])

			# Declare variable to count number of steps
			self.step_cntr = tf.Variable(0)

			# Create layers for the model
			attention_window = WindowLayer(n_gaussians=self.n_gaussians_window, n_chars=self.n_chars, str_len=str_len, C=C)
			mdn_unit = MDNLayer(n_gaussians=self.n_gaussians_mdn)
			
			lstm_network = HiddenLayers(n_layers=self.n_layers, n_units=self.n_units, batch_size=self.batch_size, window_layer=attention_window)
			# Unroll lstm network over timesteps
			obtained_output, final_states = tf.nn.dynamic_rnn(lstm_network, inputs, initial_state=lstm_network.states)

			# Pass output of LSTM network to MDN unit
			e, pi, mu_x, mu_y, sigma_x, sigma_y, rho = mdn_unit(obtained_output, self.bias)
			
			# Calculate loss using above parameters and correct output
			# Add a small quantity to make computations stable
			epsilon = 1e-8 
			corr_x, corr_y, corr_e = tf.unstack(tf.expand_dims(output, axis=3), axis=2)
			norm_x = (corr_x - mu_x)/(sigma_x + epsilon)
			norm_y = (corr_y - mu_y)/(sigma_y + epsilon)
			mrho = 1 - tf.square(rho)
			Z = norm_x**2 + norm_y**2 - 2*norm_x*norm_y*rho
			factor = 1.0/(2*np.pi*sigma_x*sigma_y*tf.sqrt(mrho) + epsilon)
			val = pi*factor*tf.exp(-Z/(2*mrho + epsilon))
			val = val * (corr_e*e + (1-corr_e)*(1-e))
			# Take sum over all timesteps and average over all batch members, 'M' gaussians
			# Dimension of 'val' is [batch_size, seq_len, n_gaussians_mdn]
			loss = tf.reduce_mean(-tf.log(epsilon + tf.reduce_sum(val, axis=2)))

			# Save these parameters/variables for accessing later
			self.params = {
				'loss':loss, 
				'input':inputs, 
				'output':output, 
				'C':C, 
				'prediction':obtained_output, 
				'steps':self.step_cntr, 
				'incr_step':self.step_cntr.assign_add(1),
				'phi':final_states[-3],
				'e':e, 'pi':pi, 'mu_x':mu_x, 'mu_y':mu_y, 
				'sigma_x':sigma_x, 'sigma_y':sigma_y, 'rho':rho,
				}
	
	def train(self, points, C, restore=False, n_epochs=50, initial_learning_rate=1e-6, load_path=None, save_path=None):
		# Split points into training data
		tr_d = [(pts[:,:-1,:], pts[:,1:,:]) for pts in points]
		
		# Create session using generated graph 
		with tf.Session(graph=self.graph) as sess:

			saver = tf.train.Saver(max_to_keep=2)

			# Create optimizer
			learning_rate = tf.train.exponential_decay(initial_learning_rate, global_step=self.params['steps'], decay_steps=1000, decay_rate=0.5)
			optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
			
			# Clip gradients to prevent 'nan' values
			grads, variables = map(list, zip(*optimizer.compute_gradients(self.params['loss'])))
			grads, _ = tf.clip_by_global_norm(grads, 5.0)
			backprop = optimizer.apply_gradients(zip(grads, variables))

			sess.run(tf.global_variables_initializer())
			
			# Restore saved model if required
			if restore:
				saver.restore(sess, tf.train.latest_checkpoint(load_path))
				st_epoch = sess.run(self.params['steps']) // len(C)
				print("Loaded trained model, starting from epoch %d."%(st_epoch+1))
			else:
				st_epoch = 0

			for n in range(st_epoch, n_epochs):
				batch_cntr = 1
				for dp, c in zip(tr_d, C):
					delta = time.time()
					_, loss, _ = sess.run([backprop, self.params['loss'], self.params['incr_step']], feed_dict={self.params['input']:dp[0], self.params['output']:dp[1], self.params['C']:c})
					delta = time.time() - delta
					print("Epoch %d/%d, batch %d/%d, loss %.4f, time %.3f sec" % (n+1, n_epochs, batch_cntr, len(C), loss, delta))
					batch_cntr += 1
				# Save model after every epoch
				saver.save(sess, save_path, global_step=self.params['steps'].eval())

        def gaussian_sample(self, e, mu_x, mu_y, sg_x, sg_y, rho):
                cov = np.array([ [sg_x*sg_x, sg_x*sg_y*rho],
                                 [sg_x*sg_y*rho, sg_y*sg_y]])
                mean = np.array([mu_x, mu_y])
                x,y = np.random.multivariate_normal(mean. cov)
                end_stroke = np.random.binomial(1, e)
                return np.array([x, y, end])

        def generate(self, string, load_path=None):
                char_mapping = utilities.map_strings([], 'save/mapping')

                # Encoding the input string
                one_hot = utilities.generate_char_encoding(string, char_mapping)
                inputs = utilities.prediction_input(string, np.array([0, 0, 0]), self.batch_size)
                self.phi = []
                self.coordinates = []
                self.coordinates.append(np.array([0, 0, 0]))
                writing_flag = True
                str_len = len(string)
                counter = 0
                phi_data = []

                # Creating the session
                with tf.Session(graph=self.graph) as sess:
                        saver = tf.train.Saver(max_to_keep = 2)
                        
                        # Loading the trained params
                        saver.restore(sess, tf.train.latest_checkpoint(load_path))
                        while(writing_flag && counter < str_len*100)
                                e, pi, mu_x, mu_y, sigma_x, sigma_y, rho, phi = sess.run([self.parmas['e'], 
                                        self.parmas['pi'], self.parmas['mu_x'],
                                        self.parmas['mu_y'], self.parmas['sigma_x'],
                                        self.parmas['sigma_y'], self.parmas['rho'],
                                        self.parmas['phi']],
                                        feed_dict = {self.params['input']:inputs[1],
                                                self.params['C']:c})


                                phi_data.append(phi[0, :])
                                g = np.random.choice(np.arrange(pi.shape[1]), p=pi[0])
                                point = self.gaussian_sample(e[0,0], mu_x[0, g], mu_y[0, g],
                                                sigma_x[0, g], sigma_y[0, g], rho[0, g])
                                self.coordinates.append(point)
                                
                                finish = tf.cast(phi[0, 0, -1] > tf.reduce_max(phi[0, 0, :-1]), tf.float)
                                if finish < 0.8:
                                        inputs = utilities.prediction_input(string, point, self.batch_size)
                                else:
                                        writing_flag = false
                                        print('\n Sampling done')

                #plotting
                
                points = [[[],[]]]
                for pts in self.coordinates:
                        points[-1][0].append(pts[0])
                        points[-1][1].append(pts[1])
                        if pts[2] == 1.:
                                points.append([[],[]])

                plt.figure()
                for pts in points:
                        plt.plot(pts[0], pts[1])
                plt.show()
