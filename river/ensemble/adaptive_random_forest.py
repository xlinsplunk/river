import abc
import collections
import math
import typing
import copy

import numpy as np

from river import base
from river.drift import ADWIN
from river.metrics import Accuracy
from river.metrics import MSE
from river.metrics.base import MultiClassMetric
from river.metrics.base import RegressionMetric
from river.tree import HoeffdingTreeClassifier
from river.tree import HoeffdingTreeRegressor
from river.tree._nodes import RandomLearningNodeMC  # noqa
from river.tree._nodes import RandomLearningNodeNB  # noqa
from river.tree._nodes import RandomLearningNodeNBA  # noqa
from river.tree._nodes import RandomLearningNodeMean  # noqa
from river.tree._nodes import RandomLearningNodeModel  # noqa
from river.tree._nodes import RandomLearningNodeAdaptive  # noqa
from river.stats import Var
from river.utils.skmultiflow_utils import check_random_state


class BaseForest(base.EnsembleMixin):

    _FEATURES_SQRT = "sqrt"
    _FEATURES_LOG2 = "log2"

    def __init__(
        self,
        n_models: int,
        max_features: typing.Union[bool, str, int],
        lambda_value: int,
        drift_detector: typing.Union[base.DriftDetector, None],
        warning_detector: typing.Union[base.DriftDetector, None],
        metric: typing.Union[MultiClassMetric, RegressionMetric],
        disable_weighted_vote,
        seed,
    ):
        super().__init__([None])  # List of models is properly initialized later
        self.models = []
        self.n_models = n_models
        self.max_features = max_features
        self.lambda_value = lambda_value
        self.metric = metric
        self.disable_weighted_vote = disable_weighted_vote
        self.drift_detector = drift_detector
        self.warning_detector = warning_detector
        self.seed = seed
        self._rng = check_random_state(self.seed)  # Actual random number generator

        # Internal parameters
        self._n_samples_seen = 0
        self._base_member_class = None

    def learn_one(self, x: dict, y: base.typing.Target, **kwargs):
        self._n_samples_seen += 1

        if not self.models:
            self._init_ensemble(list(x.keys()))

        for model in self.models:
            # Get prediction for instance
            y_pred = model.predict_one(x)

            # Update performance evaluator
            model.metric.update(y_true=y, y_pred=y_pred)

            k = self._rng.poisson(lam=self.lambda_value)
            if k > 0:
                # print(self._n_samples_seen)
                model.learn_one(x=x, y=y, sample_weight=k, n_samples_seen=self._n_samples_seen)

        return self

    def _init_ensemble(self, features: list):
        self._set_max_features(len(features))

        # Generate a different random seed per tree
        seeds = self._rng.randint(0, 4294967295, size=self.n_models, dtype="u8")

        self.models = [
            self._base_member_class(
                index_original=i,
                model=self._new_base_model(seed=seeds[i]),
                created_on=self._n_samples_seen,
                drift_detector=self.drift_detector,
                warning_detector=self.warning_detector,
                is_background_learner=False,
                metric=self.metric,
            )
            for i in range(self.n_models)
        ]

    @abc.abstractmethod
    def _new_base_model(self, seed: int):
        raise NotImplementedError

    def _set_max_features(self, n_features):
        if self.max_features == "sqrt":
            self.max_features = round(math.sqrt(n_features))
        elif self.max_features == "log2":
            self.max_features = round(math.log2(n_features))
        elif isinstance(self.max_features, int):
            # Consider 'max_features' features at each split.
            pass
        elif isinstance(self.max_features, float):
            # Consider 'max_features' as a percentage
            self.max_features = int(self.max_features * n_features)
        elif self.max_features is None:
            self.max_features = n_features
        else:
            raise AttributeError(
                f"Invalid max_features: {self.max_features}.\n"
                f"Valid options are: int [2, M], float (0., 1.],"
                f" {self._FEATURES_SQRT}, {self._FEATURES_LOG2}"
            )
        # Sanity checks
        # max_features is negative, use max_features + n
        if self.max_features < 0:
            self.max_features += n_features
        # max_features <= 0
        # (m can be negative if max_features is negative and abs(max_features) > n),
        # use max_features = 1
        if self.max_features <= 0:
            self.max_features = 1
        # max_features > n, then use n
        if self.max_features > n_features:
            self.max_features = n_features

    def reset(self):
        """Reset the forest."""
        self.models = []
        self._n_samples_seen = 0
        self._rng = check_random_state(self.seed)


class BaseTreeClassifier(HoeffdingTreeClassifier):
    """Adaptive Random Forest Hoeffding Tree Classifier.

    This is the base-estimator of the Adaptive Random Forest classifier.
    This variant of the Hoeffding Tree classifier includes the `max_features`
    parameter, which defines the number of randomly selected features to be
    considered at each split.

    """

    def __init__(
        self,
        max_features: int = 2,
        grace_period: int = 200,
        max_depth: int = None,
        split_criterion: str = "info_gain",
        split_confidence: float = 1e-7,
        tie_threshold: float = 0.05,
        leaf_prediction: str = "nba",
        nb_threshold: int = 0,
        nominal_attributes: list = None,
        attr_obs: str = "gaussian",
        attr_obs_params: dict = None,
        seed=None,
        **kwargs,
    ):
        super().__init__(
            grace_period=grace_period,
            max_depth=max_depth,
            split_criterion=split_criterion,
            split_confidence=split_confidence,
            tie_threshold=tie_threshold,
            leaf_prediction=leaf_prediction,
            nb_threshold=nb_threshold,
            nominal_attributes=nominal_attributes,
            attr_obs=attr_obs,
            attr_obs_params=attr_obs_params,
            **kwargs,
        )

        super().__init__(
            grace_period=grace_period,
            max_depth=max_depth,
            split_criterion=split_criterion,
            split_confidence=split_confidence,
            tie_threshold=tie_threshold,
            leaf_prediction=leaf_prediction,
            nb_threshold=nb_threshold,
            nominal_attributes=nominal_attributes,
            attr_obs=attr_obs,
            attr_obs_params=attr_obs_params,
            **kwargs,
        )

        self.max_features = max_features
        self.seed = seed
        self._rng = check_random_state(self.seed)

    def _new_learning_node(self, initial_stats=None, parent=None):
        if initial_stats is None:
            initial_stats = {}

        if parent is None:
            depth = 0
        else:
            depth = parent.depth + 1

        # Generate a random seed for the new learning node
        seed = self._rng.randint(0, 4294967295, dtype="u8")

        if self._leaf_prediction == self._MAJORITY_CLASS:
            return RandomLearningNodeMC(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
            )
        elif self._leaf_prediction == self._NAIVE_BAYES:
            return RandomLearningNodeNB(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
            )
        else:  # NAIVE BAYES ADAPTIVE (default)
            return RandomLearningNodeNBA(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
            )

    def new_instance(self):
        new_instance = self.clone()
        # Use existing rng to enforce a different model
        new_instance._rng = self._rng
        return new_instance


class BaseTreeRegressor(HoeffdingTreeRegressor):
    """ARF Hoeffding Tree regressor.

    This is the base-estimator of the Adaptive Random Forest regressor.
    This variant of the Hoeffding Tree regressor includes the `max_features`
    parameter, which defines the number of randomly selected features to be
    considered at each split.

    """

    def __init__(
        self,
        max_features: int = 2,
        grace_period: int = 200,
        max_depth: int = None,
        split_confidence: float = 1e-7,
        tie_threshold: float = 0.05,
        leaf_prediction: str = "model",
        leaf_model: base.Regressor = None,
        model_selector_decay: float = 0.95,
        nominal_attributes: list = None,
        attr_obs: str = "gaussian",
        attr_obs_params: dict = None,
        min_samples_split: int = 5,
        seed=None,
        **kwargs,
    ):
        super().__init__(
            grace_period=grace_period,
            max_depth=max_depth,
            split_confidence=split_confidence,
            tie_threshold=tie_threshold,
            leaf_prediction=leaf_prediction,
            leaf_model=leaf_model,
            model_selector_decay=model_selector_decay,
            nominal_attributes=nominal_attributes,
            attr_obs=attr_obs,
            attr_obs_params=attr_obs_params,
            min_samples_split=min_samples_split,
            **kwargs,
        )

        self.max_features = max_features
        self.seed = seed
        self._rng = check_random_state(self.seed)

    def _new_learning_node(self, initial_stats=None, parent=None):  # noqa
        """Create a new learning node.

        The type of learning node depends on the tree configuration.
        """

        if parent is not None:
            depth = parent.depth + 1
        else:
            depth = 0

        # Generate a random seed for the new learning node
        seed = self._rng.randint(0, 4294967295, dtype="u8")

        if self.leaf_prediction in {self._MODEL, self._ADAPTIVE}:
            if parent is None:
                leaf_model = copy.deepcopy(self.leaf_model)
            else:
                leaf_model = copy.deepcopy(parent._leaf_model)  # noqa

        if self.leaf_prediction == self._TARGET_MEAN:
            return RandomLearningNodeMean(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
            )
        elif self.leaf_prediction == self._MODEL:
            return RandomLearningNodeModel(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
                leaf_model=leaf_model,
            )  # noqa
        else:  # adaptive learning node
            new_adaptive = RandomLearningNodeAdaptive(
                initial_stats,
                depth,
                self.attr_obs,
                self.attr_obs_params,
                self.max_features,
                seed,
                leaf_model=leaf_model,
            )  # noqa
            if parent is not None:
                new_adaptive._fmse_mean = parent._fmse_mean  # noqa
                new_adaptive._fmse_model = parent._fmse_model  # noqa

            return new_adaptive

    def new_instance(self):
        new_instance = self.clone()
        # Use existing rng to enforce a different model
        new_instance._rng = self._rng
        return new_instance


class AdaptiveRandomForestClassifier(BaseForest, base.Classifier):
    """Adaptive Random Forest classifier.

    The 3 most important aspects of Adaptive Random Forest [^1] are:

    1. inducing diversity through re-sampling

    2. inducing diversity through randomly selecting subsets of features for
       node splits

    3. drift detectors per base tree, which cause selective resets in response
       to drifts

    It also allows training background trees, which start training if a
    warning is detected and replace the active tree if the warning escalates
    to a drift.

    Parameters
    ----------
    n_models
        Number of trees in the ensemble.
    max_features
        Max number of attributes for each node split.<br/>
        - If `int`, then consider `max_features` at each split.<br/>
        - If `float`, then `max_features` is a percentage and
          `int(max_features * n_features)` features are considered per split.<br/>
        - If "sqrt", then `max_features=sqrt(n_features)`.<br/>
        - If "log2", then `max_features=log2(n_features)`.<br/>
        - If None, then ``max_features=n_features``.
    lambda_value
        The lambda value for bagging (lambda=6 corresponds to Leveraging Bagging).
    metric
        Metric used to track trees performance within the ensemble.
    disable_weighted_vote
        If `True`, disables the weighted vote prediction.
    drift_detector
        Drift Detection method. Set to None to disable Drift detection.
    warning_detector
        Warning Detection method. Set to None to disable warning detection.
    grace_period
        [*Tree parameter*] Number of instances a leaf should observe between
        split attempts.
    max_depth
        [*Tree parameter*] The maximum depth a tree can reach. If `None`, the
        tree will grow indefinitely.
    split_criterion
        [*Tree parameter*] Split criterion to use.<br/>
        - 'gini' - Gini<br/>
        - 'info_gain' - Information Gain<br/>
        - 'hellinger' - Hellinger Distance
    split_confidence
        [*Tree parameter*] Allowed error in split decision, a value closer to 0
        takes longer to decide.
    tie_threshold
        [*Tree parameter*] Threshold below which a split will be forced to break
        ties.
    leaf_prediction
        [*Tree parameter*] Prediction mechanism used at leafs.<br/>
        - 'mc' - Majority Class<br/>
        - 'nb' - Naive Bayes<br/>
        - 'nba' - Naive Bayes Adaptive
    nb_threshold
        [*Tree parameter*] Number of instances a leaf should observe before
        allowing Naive Bayes.
    nominal_attributes
        [*Tree parameter*] List of Nominal attributes. If empty, then assume that
        all attributes are numerical.
    attr_obs
        [*Tree parameter*] The Attribute Observer (AO) used to monitor the class statistics of
        numeric features and perform splits. Parameters can be passed to the AOs (when supported)
        by using `attr_obs_params`. Valid options are:</br>
        - `'bst'`: Binary Search Tree.</br>
        - `'gaussian'`: Gaussian observer. The `n_splits` used to query
         for split candidates can be adjusted (defaults to `10`).</br>
        - `'histogram'`: Histogram-based class frequency estimation.  The number of histogram
        bins (`n_bins` -- defaults to `256`) and the number of split point candidates to
        evaluate (`n_splits` -- defaults to `32`) can be adjusted.</br>
        See 'Notes' for more information about the AOs.
    attr_obs_params
        [*Tree parameter*] Parameters passed to the numeric AOs. See `attr_obs` for more
        information.
    max_size
        [*Tree parameter*] Maximum memory (MB) consumed by the tree.
    memory_estimate_period
        [*Tree parameter*] Number of instances between memory consumption checks.
    seed
        If `int`, `seed` is used to seed the random number generator;
        If `RandomState`, `seed` is the random number generator;
        If `None`, the random number generator is the `RandomState` instance
        used by `np.random`.
    kwargs
        Other parameters passed to `river.tree.BaseHoeffdingTree`.

    Notes
    -----
    Hoeffding trees rely on Attribute Observer (AO) algorithms to monitor input features
    and perform splits. Nominal features can be easily dealt with, since the partitions
    are well-defined. Numerical features, however, require more sophisticated solutions.
    Currently, three AOs are supported in `river` for classification trees:

    - *Binary Search Tree (BST)*: uses an exhaustive algorithm to find split candidates,
    similarly to batch decision trees. It ends up storing all observations between split
    attempts. This AO is the most costly one in terms of memory and processing
    time; however, it tends to yield the most accurate results when using `leaf_prediction=mc`.
    It cannot be used to calculate the Probability Density Function (PDF) of the monitored
    feature due to its binary tree nature. Hence, leaf prediction strategies other than
    the majority class will end up effectively mimicing the majority class classifier.
    This AO has no parameters.</br>
    - *Gaussian Estimator*: Approximates the numeric feature distribution by using
    a Gaussian distribution per class. The Cumulative Distribution Function (CDF) necessary to
    calculate the entropy (and, consequently, the information gain), the gini index, and
    other split criteria is then calculated using the fit feature's distribution.</br>
    - *Histogram*: approximates the numeric feature distribution using an incrementally
    maintained histogram per class. It represents a compromise between the intensive
    resource usage of BST and the strong assumptions about the feature's distribution
    used in the Gaussian Estimator. Besides that, this AO sits in the middle between the
    previous two in terms of memory usage and running time. Note that the number of
    bins affects the probability density approximation required to use leaves with
    (adaptive) naive bayes models. Hence, Histogram tends to be less accurate than the
    Gaussian estimator when adaptive or naive bayes leaves are used.

    Examples
    --------
    >>> from river import synth
    >>> from river import ensemble
    >>> from river import evaluate
    >>> from river import metrics

    >>> dataset = synth.ConceptDriftStream(seed=42, position=500,
    ...                                    width=40).take(1000)

    >>> model = ensemble.AdaptiveRandomForestClassifier(
    ...     n_models=3,
    ...     seed=42
    ... )

    >>> metric = metrics.Accuracy()

    >>> evaluate.progressive_val_score(dataset, model, metric)
    Accuracy: 72.87%

    References
    ----------
    [^1]: Heitor Murilo Gomes, Albert Bifet, Jesse Read, Jean Paul Barddal,
         Fabricio Enembreck, Bernhard Pfharinger, Geoff Holmes, Talel Abdessalem.
         Adaptive random forests for evolving data stream classification.
         In Machine Learning, DOI: 10.1007/s10994-017-5642-8, Springer, 2017.

    """

    def __init__(
        self,
        n_models: int = 10,
        max_features: typing.Union[bool, str, int] = "sqrt",
        lambda_value: int = 6,
        metric: MultiClassMetric = Accuracy(),
        disable_weighted_vote=False,
        drift_detector: typing.Union[base.DriftDetector, None] = ADWIN(delta=0.001),
        warning_detector: typing.Union[base.DriftDetector, None] = ADWIN(delta=0.01),
        # Tree parameters
        grace_period: int = 50,
        max_depth: int = None,
        split_criterion: str = "info_gain",
        split_confidence: float = 0.01,
        tie_threshold: float = 0.05,
        leaf_prediction: str = "nba",
        nb_threshold: int = 0,
        nominal_attributes: list = None,
        attr_obs: str = "gaussian",
        attr_obs_params: dict = None,
        max_size: int = 32,
        memory_estimate_period: int = 2000000,
        seed: int = None,
        **kwargs,
    ):
        super().__init__(
            n_models=n_models,
            max_features=max_features,
            lambda_value=lambda_value,
            metric=metric,
            disable_weighted_vote=disable_weighted_vote,
            drift_detector=drift_detector,
            warning_detector=warning_detector,
            seed=seed,
        )

        self._n_samples_seen = 0
        self._base_member_class = ForestMemberClassifier

        # Tree parameters
        self.grace_period = grace_period
        self.max_depth = max_depth
        self.split_criterion = split_criterion
        self.split_confidence = split_confidence
        self.tie_threshold = tie_threshold
        self.leaf_prediction = leaf_prediction
        self.nb_threshold = nb_threshold
        self.nominal_attributes = nominal_attributes
        self.attr_obs = attr_obs
        self.attr_obs_params = attr_obs_params
        self.max_size = max_size
        self.memory_estimate_period = memory_estimate_period
        self.kwargs = kwargs

    def _multiclass(self):
        return True

    def predict_proba_one(self, x: dict) -> typing.Dict[base.typing.ClfTarget, float]:

        y_pred = collections.Counter()

        if not self.models:
            self._init_ensemble(features=list(x.keys()))
            return y_pred

        for model in self.models:
            y_proba_temp = model.predict_proba_one(x)
            metric_value = model.metric.get()
            if not self.disable_weighted_vote and metric_value > 0.0:
                y_proba_temp = {k: val * metric_value for k, val in y_proba_temp.items()}
            y_pred.update(y_proba_temp)

        total = sum(y_pred.values())
        if total > 0:
            return {label: proba / total for label, proba in y_pred.items()}
        return y_pred

    def _new_base_model(self, seed: int):
        return BaseTreeClassifier(
            max_features=self.max_features,
            grace_period=self.grace_period,
            split_criterion=self.split_criterion,
            split_confidence=self.split_confidence,
            tie_threshold=self.tie_threshold,
            leaf_prediction=self.leaf_prediction,
            nb_threshold=self.nb_threshold,
            nominal_attributes=self.nominal_attributes,
            attr_obs=self.attr_obs,
            attr_obs_params=self.attr_obs_params,
            max_depth=self.max_depth,
            memory_estimate_period=self.memory_estimate_period,
            max_size=self.max_size,
            seed=seed,
            **self.kwargs,
        )


class AdaptiveRandomForestRegressor(BaseForest, base.Regressor):
    r"""Adaptive Random Forest regressor.

    The 3 most important aspects of Adaptive Random Forest [^1] are:

    1. inducing diversity through re-sampling

    2. inducing diversity through randomly selecting subsets of features for
       node splits

    3. drift detectors per base tree, which cause selective resets in response
       to drifts

    Notice that this implementation is slightly different from the original
    algorithm proposed in [^2]. The `HoeffdingTreeRegressor` is used as base
    learner, instead of `FIMT-DD`. It also adds a new strategy to monitor the
    predictions and check for concept drifts. The deviations of the predictions
    to the target are monitored and normalized in the [0, 1] range to fulfill ADWIN's
    requirements. We assume that the data subjected to the normalization follows
    a normal distribution, and thus, lies within the interval of the mean $\pm3\sigma$.

    Parameters
    ----------
    n_models
        Number of trees in the ensemble.
    max_features
        Max number of attributes for each node split.<br/>
        - If `int`, then consider `max_features` at each split.<br/>
        - If `float`, then `max_features` is a percentage and
          `int(max_features * n_features)` features are considered per split.<br/>
        - If "sqrt", then `max_features=sqrt(n_features)`.<br/>
        - If "log2", then `max_features=log2(n_features)`.<br/>
        - If None, then ``max_features=n_features``.
    lambda_value
        The lambda value for bagging (lambda=6 corresponds to Leveraging Bagging).
    metric
        Metric used to track trees performance within the ensemble. Depending,
        on the configuration, this metric is also used to weight predictions
        from the members of the ensemble.
    aggregation_method
        The method to use to aggregate predictions in the ensemble.<br/>
        - 'mean'<br/>
        - 'median' - If selected will disable the weighted vote.
    disable_weighted_vote
        If `True`, disables the weighted vote prediction, i.e. does not assign
        weights to individual tree's predictions and uses the arithmetic mean
        instead. Otherwise will use the `metric` value to weight predictions.
    drift_detector
        Drift Detection method. Set to None to disable Drift detection.
    warning_detector
        Warning Detection method. Set to None to disable warning detection.
    grace_period
        [*Tree parameter*] Number of instances a leaf should observe between
        split attempts.
    max_depth
        [*Tree parameter*] The maximum depth a tree can reach. If `None`, the
        tree will grow indefinitely.
    split_confidence
        [*Tree parameter*] Allowed error in split decision, a value closer to 0
        takes longer to decide.
    tie_threshold
        [*Tree parameter*] Threshold below which a split will be forced to break
        ties.
    leaf_prediction
        [*Tree parameter*] Prediction mechanism used at leaves.</br>
        - 'mean' - Target mean</br>
        - 'model' - Uses the model defined in `leaf_model`</br>
        - 'adaptive' - Chooses between 'mean' and 'model' dynamically</br>
    leaf_model
        [*Tree parameter*] The regression model used to provide responses if
        `leaf_prediction='model'`. If not provided, an instance of
        `river.linear_model.LinearRegression` with the default hyperparameters
         is used.
    model_selector_decay
        The exponential decaying factor applied to the learning models' squared
        errors, that are monitored if `leaf_prediction='adaptive'`. Must be
        between `0` and `1`. The closer to `1`, the more importance is going to
        be given to past observations. On the other hand, if its value
        approaches `0`, the recent observed errors are going to have more
        influence on the final decision.
    nominal_attributes
        [*Tree parameter*] List of Nominal attributes. If empty, then assume that
        all attributes are numerical.
    attr_obs
        [*Tree parameter*] The attribute observer (AO) used to monitor the target
        statistics of numeric features and perform splits. Parameters can be passed to the
        AOs (when supported) by using `attr_obs_params`. Valid options are:</br>
        - `'e-bst'`: Extended Binary Search Tree (E-BST). This AO has no parameters.</br>
        See notes for more information about the supported AOs.
    attr_obs_params
        [*Tree parameter*] Parameters passed to the numeric AOs. See `attr_obs`
        for more information.
    min_samples_split
        [*Tree parameter*] The minimum number of samples every branch resulting from a split
        candidate must have to be considered valid.
    max_size
        [*Tree parameter*] Maximum memory (MB) consumed by the tree.
    memory_estimate_period
        [*Tree parameter*] Number of instances between memory consumption checks.
    seed
        If `int`, `seed` is used to seed the random number generator;
        If `RandomState`, `seed` is the random number generator;
        If `None`, the random number generator is the `RandomState` instance
        used by `np.random`.
    kwargs
        Other parameters passed to `river.tree.BaseHoeffdingTree`.

    Notes
    -----
    Hoeffding trees rely on Attribute Observer (AO) algorithms to monitor input features
    and perform splits. Nominal features can be easily dealt with, since the partitions
    are well-defined. Numerical features, however, require more sophisticated solutions.
    Currently, only one AO is supported in `river` for regression trees:

    - The Extended Binary Search Tree (E-BST) uses an exhaustive algorithm to find split
    candidates, similarly to batch decision tree algorithms. It ends up storing all
    observations between split attempts. However, E-BST automatically removes bad split
    points periodically from its structure and, thus, alleviates the memory and time
    costs involved in its usage.

    References
    ----------
    [^1]: Gomes, H.M., Bifet, A., Read, J., Barddal, J.P., Enembreck, F.,
          Pfharinger, B., Holmes, G. and Abdessalem, T., 2017. Adaptive random
          forests for evolving data stream classification. Machine Learning,
          106(9-10), pp.1469-1495.

    [^2]: Gomes, H.M., Barddal, J.P., Boiko, L.E., Bifet, A., 2018.
          Adaptive random forests for data stream regression. ESANN 2018.

    Examples
    --------
    >>> from river import datasets
    >>> from river import evaluate
    >>> from river import metrics
    >>> from river import ensemble
    >>> from river import preprocessing

    >>> dataset = datasets.TrumpApproval()

    >>> model = (
    ...     preprocessing.StandardScaler() |
    ...     ensemble.AdaptiveRandomForestRegressor(n_models=3, seed=42)
    ... )

    >>> metric = metrics.MAE()

    >>> evaluate.progressive_val_score(dataset, model, metric)
    MAE: 23.320694

    """

    _MEAN = "mean"
    _MEDIAN = "median"
    _VALID_AGGREGATION_METHOD = [_MEAN, _MEDIAN]

    def __init__(
        self,
        # Forest parameters
        n_models: int = 10,
        max_features="sqrt",
        aggregation_method: str = "median",
        lambda_value: int = 6,
        metric: RegressionMetric = MSE(),
        disable_weighted_vote=False,
        drift_detector: base.DriftDetector = ADWIN(0.001),
        warning_detector: base.DriftDetector = ADWIN(0.01),
        # Tree parameters
        grace_period: int = 50,
        max_depth: int = None,
        split_confidence: float = 0.01,
        tie_threshold: float = 0.05,
        leaf_prediction: str = "model",
        leaf_model: base.Regressor = None,
        model_selector_decay: float = 0.95,
        nominal_attributes: list = None,
        attr_obs: str = "e-bst",
        attr_obs_params: dict = None,
        min_samples_split: int = 5,
        max_size: int = 100,
        memory_estimate_period: int = 2000000,
        seed: int = None,
        **kwargs,
    ):
        super().__init__(
            n_models=n_models,
            max_features=max_features,
            lambda_value=lambda_value,
            metric=metric,
            disable_weighted_vote=disable_weighted_vote,
            drift_detector=drift_detector,
            warning_detector=warning_detector,
            seed=seed,
        )

        self._n_samples_seen = 0
        self._base_member_class = ForestMemberRegressor

        # Tree parameters
        self.grace_period = grace_period
        self.max_depth = max_depth
        self.split_confidence = split_confidence
        self.tie_threshold = tie_threshold
        self.leaf_prediction = leaf_prediction
        self.leaf_model = leaf_model
        self.model_selector_decay = model_selector_decay
        self.nominal_attributes = nominal_attributes
        self.attr_obs = attr_obs
        self.attr_obs_params = attr_obs_params
        self.min_samples_split = min_samples_split
        self.max_size = max_size
        self.memory_estimate_period = memory_estimate_period
        self.kwargs = kwargs

        if aggregation_method in self._VALID_AGGREGATION_METHOD:
            self.aggregation_method = aggregation_method
        else:
            raise ValueError(
                f"Invalid aggregation_method: {aggregation_method}.\n"
                f"Valid values are: {self._VALID_AGGREGATION_METHOD}"
            )

    def predict_one(self, x: dict) -> base.typing.RegTarget:

        if not self.models:
            self._init_ensemble(features=list(x.keys()))
            return 0.0

        y_pred = np.zeros(self.n_models)

        if not self.disable_weighted_vote:
            weights = np.zeros(self.n_models)
            sum_weights = 0.0
            for idx, model in enumerate(self.models):
                y_pred[idx] = model.predict_one(x)
                weights[idx] = model.metric.get()
                sum_weights += weights[idx]

            if sum_weights != 0:
                # The higher the error, the worse is the tree
                weights = sum_weights - weights
                # Normalize weights to sum up to 1
                weights = weights / weights.sum()
                y_pred *= weights
        else:
            for idx, model in enumerate(self.models):
                y_pred[idx] = model.predict_one(x)

        if self.aggregation_method == self._MEAN:
            y_pred = y_pred.mean()
        else:
            y_pred = np.median(y_pred)

        return y_pred

    def _new_base_model(self, seed: int):
        return BaseTreeRegressor(
            max_features=self.max_features,
            grace_period=self.grace_period,
            max_depth=self.max_depth,
            split_confidence=self.split_confidence,
            tie_threshold=self.tie_threshold,
            leaf_prediction=self.leaf_prediction,
            leaf_model=self.leaf_model,
            model_selector_decay=self.model_selector_decay,
            nominal_attributes=self.nominal_attributes,
            attr_obs=self.attr_obs,
            attr_obs_params=self.attr_obs_params,
            max_size=self.max_size,
            memory_estimate_period=self.memory_estimate_period,
            seed=seed,
            **self.kwargs,
        )

    @property
    def valid_aggregation_method(self):
        """Valid aggregation_method values."""
        return self._VALID_AGGREGATION_METHOD


class BaseForestMember:
    """Base forest member class.

    This class represents a tree member of the forest. It includes a
    base tree model, the background learner, drift detectors and performance
    tracking parameters.

    The main purpose of this class is to train the foreground model.
    Optionally, it monitors drift detection. Depending on the configuration,
    if drift is detected then the foreground model is reset or replaced by a
    background model.

    Parameters
    ----------
    index_original
        Tree index within the ensemble.
    model
        Tree learner.
    created_on
        Number of instances seen by the tree.
    drift_detector
        Drift Detection method.
    warning_detector
        Warning Detection method.
    is_background_learner
        True if the tree is a background learner.
    metric
        Metric to track performance.

    """

    def __init__(
        self,
        index_original: int,
        model: typing.Union[BaseTreeClassifier, BaseTreeRegressor],
        created_on: int,
        drift_detector: base.DriftDetector,
        warning_detector: base.DriftDetector,
        is_background_learner,
        metric: typing.Union[MultiClassMetric, RegressionMetric],
    ):
        self.index_original = index_original
        self.model = model.clone()
        self.created_on = created_on
        self.is_background_learner = is_background_learner
        self.metric = copy.deepcopy(metric)
        # Make sure that the metric is not initialized, e.g. when creating background learners.
        if isinstance(self.metric, MultiClassMetric):
            self.metric.cm.reset()
        # Keep a copy of the original metric for background learners or reset
        self._original_metric = copy.deepcopy(metric)

        self.background_learner = None

        # Drift and warning detection
        self.last_drift_on = 0
        self.last_warning_on = 0
        self.n_drifts_detected = 0
        self.n_warnings_detected = 0

        # Initialize drift and warning detectors
        if drift_detector is not None:
            self._use_drift_detector = True
            self.drift_detector = drift_detector.clone()
        else:
            self._use_drift_detector = False
            self.drift_detector = None

        if warning_detector is not None:
            self._use_background_learner = True
            self.warning_detector = warning_detector.clone()
        else:
            self._use_background_learner = False
            self.warning_detector = None

    def reset(self, n_samples_seen):
        if self._use_background_learner and self.background_learner is not None:
            # Replace foreground model with background model
            self.model = self.background_learner.model
            self.warning_detector = self.background_learner.warning_detector
            self.drift_detector = self.background_learner.drift_detector
            self.metric = self.background_learner.metric
            self.created_on = self.background_learner.created_on
            self.background_learner = None
        else:
            # Reset model
            self.model = self.model.clone()
            self.metric = copy.deepcopy(self._original_metric)
            self.created_on = n_samples_seen
            self.drift_detector = self.drift_detector.clone()
        # Make sure that the metric is not initialized, e.g. when creating background learners.
        if isinstance(self.metric, MultiClassMetric):
            self.metric.cm.reset()

    def learn_one(self, x: dict, y: base.typing.Target, *, sample_weight: int, n_samples_seen: int):

        self.model.learn_one(x, y, sample_weight=sample_weight)

        if self.background_learner:
            # Train the background learner
            self.background_learner.model.learn_one(x=x, y=y, sample_weight=sample_weight)

        if self._use_drift_detector and not self.is_background_learner:
            drift_detector_input = self._drift_detector_input(
                y_true=y, y_pred=self.model.predict_one(x)
            )

            # Check for warning only if use_background_learner is set
            if self._use_background_learner:
                self.warning_detector.update(drift_detector_input)
                # Check if there was a (warning) change
                if self.warning_detector.change_detected:
                    self.last_warning_on = n_samples_seen
                    self.n_warnings_detected += 1
                    # Create a new background learner object
                    self.background_learner = self.__class__(
                        index_original=self.index_original,
                        model=self.model.new_instance(),
                        created_on=n_samples_seen,
                        drift_detector=self.drift_detector,
                        warning_detector=self.warning_detector,
                        is_background_learner=True,
                        metric=self.metric,
                    )
                    # Reset the warning detector for the current object
                    self.warning_detector = self.warning_detector.clone()

            # Update the drift detector
            self.drift_detector.update(drift_detector_input)

            # Check if there was a change
            if self.drift_detector.change_detected:
                self.last_drift_on = n_samples_seen
                self.n_drifts_detected += 1
                self.reset(n_samples_seen)

    @abc.abstractmethod
    def _drift_detector_input(
        self,
        y_true: typing.Union[base.typing.ClfTarget, base.typing.RegTarget],
        y_pred: typing.Union[base.typing.ClfTarget, base.typing.RegTarget],
    ):
        raise NotImplementedError


class ForestMemberClassifier(BaseForestMember, base.Classifier):
    """Forest member class for classification"""

    def __init__(
        self,
        index_original: int,
        model: BaseTreeClassifier,
        created_on: int,
        drift_detector: base.DriftDetector,
        warning_detector: base.DriftDetector,
        is_background_learner,
        metric: MultiClassMetric,
    ):
        super().__init__(
            index_original=index_original,
            model=model,
            created_on=created_on,
            drift_detector=drift_detector,
            warning_detector=warning_detector,
            is_background_learner=is_background_learner,
            metric=metric,
        )

    def _drift_detector_input(self, y_true: base.typing.ClfTarget, y_pred: base.typing.ClfTarget):
        return int(not y_true == y_pred)  # Not correctly_classifies

    def predict_one(self, x):
        return self.model.predict_one(x)

    def predict_proba_one(self, x):
        return self.model.predict_proba_one(x)


class ForestMemberRegressor(BaseForestMember, base.Regressor):
    """Forest member class for regression"""

    def __init__(
        self,
        index_original: int,
        model: BaseTreeRegressor,
        created_on: int,
        drift_detector: base.DriftDetector,
        warning_detector: base.DriftDetector,
        is_background_learner,
        metric: RegressionMetric,
    ):
        super().__init__(
            index_original=index_original,
            model=model,
            created_on=created_on,
            drift_detector=drift_detector,
            warning_detector=warning_detector,
            is_background_learner=is_background_learner,
            metric=metric,
        )
        self._var = Var()  # Used to track drift

    def _drift_detector_input(self, y_true: float, y_pred: float):
        drift_input = y_true - y_pred
        self._var.update(drift_input)

        if self._var.mean.n == 1:
            return 0.5  # The expected error is the normalized mean error

        sd = math.sqrt(self._var.sigma)

        # We assume the error follows a normal distribution -> (empirical rule)
        # 99.73% of the values lie  between [mean - 3*sd, mean + 3*sd]. We
        # assume this range for the normalized data. Hence, we can apply the
        # min-max norm to cope with  ADWIN's requirements
        return (drift_input + 3 * sd) / (6 * sd) if sd > 0 else 0.5

    def reset(self, n_samples_seen):
        super().reset(n_samples_seen)
        # Reset the stats for the drift detector
        self._var = Var()

    def predict_one(self, x):
        return self.model.predict_one(x)
